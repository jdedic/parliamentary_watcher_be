from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChatAccessKey(Base):
    """Stores GUID access codes that protect the chat feature."""

    __tablename__ = "chat_access_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    max_requests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requests_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    def __repr__(self) -> str:
        return f"<ChatAccessKey id={self.id} label={self.label!r}>"
