from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.speaker import Speaker


class SpeakerRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, speaker_id: int) -> Speaker | None:
        result = await self.db.execute(
            select(Speaker).where(Speaker.id == speaker_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name_and_party(self, name: str, party: str | None) -> Speaker | None:
        result = await self.db.execute(
            select(Speaker).where(Speaker.name == name, Speaker.party_afkorting == party)
        )
        return result.scalar_one_or_none()

    async def create(self, name: str, function: str | None, party_afkorting: str | None) -> Speaker:
        speaker = Speaker(name=name, function=function, party_afkorting=party_afkorting)
        self.db.add(speaker)
        await self.db.flush()
        return speaker

    async def update_enrichment(
        self,
        speaker: Speaker,
        *,
        party_name_nl: str | None,
        party_name_en: str | None,
        tk_persoon_id: str | None,
        image_path: str | None,
        resolved_at: datetime,
    ) -> Speaker:
        speaker.party_name_nl = party_name_nl
        speaker.party_name_en = party_name_en
        speaker.tk_persoon_id = tk_persoon_id
        speaker.image_path = image_path
        speaker.resolved_at = resolved_at
        await self.db.flush()
        return speaker
