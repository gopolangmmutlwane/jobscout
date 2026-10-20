"""Read-only Gmail IMAP access for reply tracking.

Only these IMAP commands are ever issued: LOGIN, EXAMINE (select with readonly=True), SEARCH,
FETCH with BODY.PEEK (so nothing is marked as read) and LOGOUT. Nothing is deleted, moved, flagged,
copied or sent. Message bodies stay in memory; callers store at most a short snippet.
"""
import email
import imaplib
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.header import decode_header, make_header
from email.policy import default as default_policy
from email.utils import getaddresses, parsedate_to_datetime

from bs4 import BeautifulSoup

HOST, PORT = "imap.gmail.com", 993
MAILBOXES = ("INBOX", '"[Gmail]/All Mail"')
MAX_MESSAGE_BYTES = 15 * 1024 * 1024  # skip anything bigger without downloading it
BODY_KEEP_CHARS = 5000  # cleaned body kept in memory for matching and classifying
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_SIZE = re.compile(rb"RFC822\.SIZE (\d+)")


class MailboxError(RuntimeError):
    """Login or mailbox problem. The message never contains the password."""


@dataclass
class MailMessage:
    message_id: str
    received_at: datetime | None
    from_addr: str
    from_name: str
    subject: str
    body: str  # cleaned text, at most BODY_KEEP_CHARS; never stored in full


def imap_date(d: date) -> str:
    return f"{d.day:02d}-{_MONTHS[d.month - 1]}-{d.year}"


def _decode(value) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(str(value))))
    except Exception:
        return str(value)


def _part_text(part) -> str:
    try:
        text = part.get_content()
    except Exception:
        payload = part.get_payload(decode=True) or b""
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    if part.get_content_type() == "text/html":
        text = BeautifulSoup(text, "lxml").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def clean_body(msg) -> str:
    """Text of the message, whitespace collapsed, attachments ignored. Uses the plain-text part unless it
    is nearly empty (many recruitment emails ship a stub plain part), then the HTML part as text."""
    if not hasattr(msg, "get_body"):
        return ""
    plain, html = msg.get_body(preferencelist=("plain",)), msg.get_body(preferencelist=("html",))
    text = _part_text(plain) if plain is not None else ""
    if len(text) < 80 and html is not None:
        text = _part_text(html) or text
    return text[:BODY_KEEP_CHARS]


def parse_message(raw: bytes) -> MailMessage:
    msg = email.message_from_bytes(raw, policy=default_policy)
    name, addr = (getaddresses([str(msg.get("From", ""))]) or [("", "")])[0]
    try:
        received = parsedate_to_datetime(str(msg.get("Date"))) if msg.get("Date") else None
        if received is not None and received.tzinfo is not None:
            received = received.astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        received = None
    message_id = str(msg.get("Message-ID", "")).strip()
    subject = _decode(msg.get("Subject", ""))
    if not message_id:  # rare; build a stable stand-in so the message is not stored twice
        message_id = f"<no-id:{addr}:{msg.get('Date', '')}:{subject[:80]}>"
    return MailMessage(message_id=message_id[:500], received_at=received, from_addr=addr.lower(),
                       from_name=_decode(name), subject=subject, body=clean_body(msg))


def _is_own(header_from: str, subject: str, me: str) -> bool:
    _name, addr = (getaddresses([header_from]) or [("", "")])[0]
    return addr.lower() == me.lower() or subject.lower().startswith("jobscout")


def fetch_messages(since: date, address: str, password: str, connect=None, log=print) -> tuple[list[MailMessage], int]:
    """Messages received since `since` in the Inbox and All Mail, minus mail you sent and jobscout's own
    digests. Returns (messages, number of messages looked at). Read-only throughout."""
    if not address or not password:
        raise MailboxError("EMAIL_ADDRESS and EMAIL_APP_PASSWORD must be set in .env to read replies.")
    connect = connect or (lambda: imaplib.IMAP4_SSL(HOST, PORT, timeout=60))
    try:
        conn = connect()
    except OSError as e:
        raise MailboxError(f"Could not reach {HOST}:{PORT} ({e.__class__.__name__}).") from None
    try:
        try:
            conn.login(address, password)
        except imaplib.IMAP4.error:
            raise MailboxError(
                "Gmail refused the login. EMAIL_APP_PASSWORD must be a 16-character Google app password "
                "(Google Account > Security > App passwords; needs 2-Step Verification), and IMAP must be "
                "enabled in Gmail settings (See all settings > Forwarding and POP/IMAP)."
            ) from None
        seen, out, scanned = set(), [], 0
        for mailbox in MAILBOXES:
            status, _data = conn.select(mailbox, readonly=True)
            if status != "OK":
                log(f"[replies] could not open {mailbox}; skipped")
                continue
            status, data = conn.search(None, "SINCE", imap_date(since))
            if status != "OK" or not data or not data[0]:
                continue
            for num in data[0].split():
                status, head = conn.fetch(num, "(RFC822.SIZE BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE)])")
                if status != "OK" or not head or not isinstance(head[0], tuple):
                    continue
                size_m = _SIZE.search(head[0][0])
                hdr = email.message_from_bytes(head[0][1], policy=default_policy)
                mid = str(hdr.get("Message-ID", "")).strip()
                if mid and mid in seen:
                    continue  # the same message appears in both Inbox and All Mail
                if mid:
                    seen.add(mid)
                scanned += 1
                if _is_own(str(hdr.get("From", "")), _decode(hdr.get("Subject", "")), address):
                    continue
                if size_m and int(size_m.group(1)) > MAX_MESSAGE_BYTES:
                    continue
                status, full = conn.fetch(num, "(BODY.PEEK[])")
                if status != "OK" or not full or not isinstance(full[0], tuple):
                    continue
                message = parse_message(full[0][1])
                if not mid:
                    if message.message_id in seen:
                        continue
                    seen.add(message.message_id)
                out.append(message)
        return out, scanned
    finally:
        try:
            conn.logout()
        except Exception:
            pass
