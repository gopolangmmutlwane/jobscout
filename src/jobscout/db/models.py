from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    closing_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)  # for dedupe
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=_now)
    match_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="new")  # new/shortlisted/tailored/applied/skipped

    labels: Mapped[list["Label"]] = relationship(back_populates="job")


class Label(Base):
    """Your feedback on a job. This is the training data for the classifier."""
    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    label: Mapped[str] = mapped_column(String(20))  # interested / skip
    labelled_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    job: Mapped["Job"] = relationship(back_populates="labels")


class Run(Base):
    """One execution of the pipeline, for tracking and debugging."""
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Application(Base):
    """One row per job you applied to."""
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    applied_on: Mapped[date] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), default="applied")
    follow_up_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class EmailEvent(Base):
    """A reply in the mailbox linked to one of your applications. Only a short snippet of the
    body is kept: never the full body or attachments."""
    __tablename__ = "email_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(500), unique=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    from_addr: Mapped[str] = mapped_column(String(320))
    from_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    subject: Mapped[str] = mapped_column(String(500), default="")
    snippet: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)  # first 300 chars, cleaned
    category: Mapped[str] = mapped_column(String(20))  # acknowledgement/assessment/interview/offer/rejection/other
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    match_reason: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    handled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ApplicationDocument(Base):
    """A file you saved for a job (CV, cover letter, ...). The file lives in
    data/applications/<job_id>/<stored_name>; original_name is only ever shown, never used as a path."""
    __tablename__ = "application_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # cv / cover_letter / other
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(64), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
