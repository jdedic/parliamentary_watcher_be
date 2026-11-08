from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.repositories.speaker_repository import SpeakerRepository
from app.schemas.speaker import SpeakerSchema
from app.services.speaker_service import enrich_speaker

router = APIRouter(prefix="/speakers", tags=["Speakers"])

logger = get_logger(__name__)


def _to_schema(speaker) -> SpeakerSchema:
    return SpeakerSchema(
        id=speaker.id,
        name=speaker.name,
        function=speaker.function,
        party_afkorting=speaker.party_afkorting,
        party_name_nl=speaker.party_name_nl,
        party_name_en=speaker.party_name_en,
        image_url=f"/api/v1/speakers/{speaker.id}/image",
        resolved=speaker.resolved_at is not None,
    )


@router.get("/{speaker_id}", response_model=SpeakerSchema, summary="Get speaker details")
async def get_speaker(
    speaker_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> SpeakerSchema:
    repo = SpeakerRepository(db)
    speaker = await repo.get_by_id(speaker_id)
    if speaker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Speaker not found")

    if speaker.resolved_at is None:
        try:
            speaker = await enrich_speaker(db, speaker)
            await db.commit()
            await db.refresh(speaker)
        except Exception as exc:
            logger.error("speaker_enrichment_failed", speaker_id=speaker_id, error=str(exc), exc_info=True)
            await db.rollback()

    return _to_schema(speaker)


@router.get("/{speaker_id}/image", summary="Get speaker photo (or placeholder)")
async def get_speaker_image(
    speaker_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> FileResponse:
    repo = SpeakerRepository(db)
    speaker = await repo.get_by_id(speaker_id)
    if speaker is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Speaker not found")

    if speaker.image_path and Path(speaker.image_path).exists():
        return FileResponse(speaker.image_path)
    return FileResponse(settings.speaker_placeholder_image_path)
