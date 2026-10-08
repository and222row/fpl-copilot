from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.fpl import utcnow


class JobRun(Base):
    """
    One run of a background job, so its health survives restarts.

    The refresh is triggered from outside (QStash, GitHub Actions) and Render's
    free instance forgets everything when it idles, so without this the only
    record of a failed run would be a log line nobody was watching. Rows older
    than RETENTION_DAYS are pruned on each write.
    """
    __tablename__ = "job_runs"
    __table_args__ = (Index("ix_job_runs_job_started", "job", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    # Step name -> short error message. Messages only: no payloads.
    errors: Mapped[Any] = mapped_column(JSON, default=list)
