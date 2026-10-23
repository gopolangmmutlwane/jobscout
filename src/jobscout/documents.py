"""Per-job file storage: data/applications/<job_id>/<random hex>.<ext>.

The uploaded file name is never used to build a path: it is kept only in the database (for display and
as the download name). A file is accepted only when its extension AND its first bytes say pdf, docx or doc.
"""
import io
import re
import secrets
import zipfile
from pathlib import Path

ALLOWED = {"pdf": "application/pdf",
           "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
           "doc": "application/msword"}
KINDS = {"cv": "CV", "cover_letter": "Cover letter", "other": "Other"}
MAX_BYTES = 10 * 1024 * 1024
MAX_FILES = 10
_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_STORED = re.compile(r"^[0-9a-f]{32}\.(pdf|docx|doc)$")


class UploadRejected(ValueError):
    """The upload is refused; the message is shown to you as is."""


def display_name(filename: str) -> str:
    """Last path component of the uploaded name, control characters removed. For display only."""
    name = re.split(r"[\\/]", filename or "")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    return name[:255] or "file"


def extension(filename: str) -> str:
    name = display_name(filename)
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def sniff(data: bytes) -> str | None:
    """pdf / docx / doc from the file's first bytes, or None."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(_OLE2):
        return "doc"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
        except zipfile.BadZipFile:
            return None
        if "word/document.xml" in names and "[Content_Types].xml" in names:
            return "docx"
    return None


def check_upload(filename: str, data: bytes, existing_count: int) -> str:
    """Returns the file type (pdf/docx/doc) or raises UploadRejected with a clear message."""
    if existing_count >= MAX_FILES:
        raise UploadRejected(f"This ad already has {MAX_FILES} files, the maximum. Delete one first.")
    if not data:
        raise UploadRejected("The file is empty.")
    if len(data) > MAX_BYTES:
        raise UploadRejected("The file is larger than 10 MB.")
    ext = extension(filename)
    if ext not in ALLOWED:
        raise UploadRejected("Only PDF, DOCX or DOC files can be saved.")
    real = sniff(data)
    if real is None:
        raise UploadRejected(f"This is not a real {ext.upper()} file. Only PDF, DOCX or DOC files can be saved.")
    if real != ext:
        raise UploadRejected(f"The file says .{ext} but its content is {real.upper()}. Rename it to .{real} and try again.")
    return real


def new_stored_name(ext: str) -> str:
    return f"{secrets.token_hex(16)}.{ext}"


def job_dir(base: Path, job_id: int) -> Path:
    return Path(base) / str(int(job_id))


def file_path(base: Path, job_id: int, stored_name: str) -> Path:
    """Where a stored file lives. stored_name comes from the database and must look like ours."""
    if not _STORED.match(stored_name or ""):
        raise ValueError("unexpected stored name")
    folder = job_dir(base, job_id).resolve()
    path = (folder / stored_name).resolve()
    if path.parent != folder:
        raise ValueError("path outside the job folder")
    return path


def header_name(filename: str) -> str:
    """Download name safe for a Content-Disposition header: no control characters, quotes, backslashes
    or semicolons."""
    name = display_name(filename)
    return "".join(c if c.isprintable() and c not in '"\\;' else "_" for c in name)


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / (1024 * 1024):.1f} MB"
