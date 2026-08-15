from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Speaker(Base):
    """Normalized speaker entity, resolved from free-text stance speaker/party pairs."""

    __tablename__ = "speakers"
    __table_args__ = (UniqueConstraint("name", "party_afkorting", name="uq_speakers_name_party"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    function: Mapped[str | None] = mapped_column(String(200), nullable=True)
    party_afkorting: Mapped[str | None] = mapped_column(String(20), nullable=True)
    party_name_nl: Mapped[str | None] = mapped_column(String(200), nullable=True)
    party_name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tk_persoon_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    def __repr__(self) -> str:
        return f"<Speaker id={self.id} name={self.name!r} party={self.party_afkorting!r}>"
