from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Integer, String, Text, ForeignKey, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class SessionStatus(str, Enum):
    DOWNLOADED = "DOWNLOADED"
    FAILED = "FAILED"
    CHUNK_SUMMARISED = "CHUNK_SUMMARISED"
    SUMMARISED = "SUMMARISED"


class PlenarySession(Base):
    """Represents a plenary session from the Tweede Kamer API."""

    __tablename__ = "plenary_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    room: Mapped[str | None] = mapped_column(String, nullable=True)
    parliamentary_year: Mapped[str | None] = mapped_column(String, nullable=True)
    meeting_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chamber: Mapped[str | None] = mapped_column(String, nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    api_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    chair: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[SessionStatus | None] = mapped_column(
        SAEnum(SessionStatus, name="sessionstatus"), nullable=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    stances: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_sources: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    stances_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    current_verslag_id: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    documents: Mapped[list["PlenarySessionDocument"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<PlenarySession id={self.id} title={self.title}>"


class PlenarySessionDocument(Base):
    """Represents a downloaded XML document linked to a plenary session."""

    __tablename__ = "plenary_session_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("plenary_sessions.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    downloaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    session: Mapped["PlenarySession"] = relationship(back_populates="documents")

    def __repr__(self) -> str:
        return f"<PlenarySessionDocument session_id={self.session_id} document_id={self.document_id}>"
