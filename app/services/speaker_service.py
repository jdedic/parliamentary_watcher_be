from datetime import datetime, timezone
from pathlib import Path

import aiofiles
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.http_client import (
    download_persoon_photo,
    fetch_fractie_by_afkorting,
    fetch_fractie_for_fractiezetel,
    fetch_fractiezetel_persoon,
    fetch_persoon_candidates,
)
from app.core.logging import get_logger
from app.models.speaker import Speaker
from app.repositories.speaker_repository import SpeakerRepository

logger = get_logger(__name__)


async def get_or_create_speaker(
    db: AsyncSession, name: str | None, party: str | None, function: str | None = None
) -> Speaker | None:
    """
    DB-only lookup/create — no network calls, safe to call inline during stance extraction.

    Returns None if there is no usable speaker name (e.g. missing/blank).
    """
    if not name:
        return None

    repo = SpeakerRepository(db)
    speaker = await repo.get_by_name_and_party(name, party)
    if speaker is not None:
        return speaker

    return await repo.create(name=name, function=function, party_afkorting=party)


_TUSSENVOEGSELS = {
    "van", "de", "der", "den", "ten", "ter", "op", "aan", "in", "uit", "onder", "over", "'t",
    "el", "al",
}


def _guess_surname(name: str) -> str:
    """
    Best-effort surname extraction from a display name.

    The Tweede Kamer transcript XML reverses tussenvoegsel order in its <achternaam>
    field (e.g. "Diederik van Dijk" is stored as achternaam="Dijk van"), so the true
    surname is the token before any trailing tussenvoegsel words, not the last token.
    """
    tokens = name.strip().split(" ")
    while len(tokens) > 1 and tokens[-1].lower() in _TUSSENVOEGSELS:
        tokens = tokens[:-1]
    return tokens[-1]


async def _resolve_party_membership_match(persoon_id: str, target_afkorting: str) -> bool:
    """
    Check whether this person's MOST RECENT party-seat membership matches the given
    abbreviation. Deliberately checks only the latest membership (fetch_fractiezetel_persoon
    orders by Van desc) rather than full history — otherwise two different people who both
    held the same party at different points in time (e.g. decades apart) collide.
    """
    try:
        memberships = await fetch_fractiezetel_persoon(persoon_id)
    except (httpx.HTTPStatusError, httpx.RequestError):
        return False

    if not memberships:
        return False

    fractiezetel_id = memberships[0].get("FractieZetel_Id")
    if not fractiezetel_id:
        return False

    try:
        fractie = await fetch_fractie_for_fractiezetel(fractiezetel_id)
    except (httpx.HTTPStatusError, httpx.RequestError):
        return False

    return bool(fractie and fractie.get("Afkorting") == target_afkorting)


def _first_name_matches(candidate: dict, given_name: str) -> bool:
    """Check whether the speaker's first name token appears in the candidate's Roepnaam/Voornamen."""
    first_token = given_name.strip().split(" ")[0].lower()
    roepnaam = (candidate.get("Roepnaam") or "").lower()
    voornamen = (candidate.get("Voornamen") or "").lower()
    return first_token in roepnaam or first_token in voornamen


async def _resolve_person(speaker: Speaker) -> dict | None:
    """Best-effort match of a speaker to a Tweede Kamer Persoon record. May return None."""
    surname = _guess_surname(speaker.name)
    try:
        candidates = await fetch_persoon_candidates(surname)
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.warning("speaker_persoon_lookup_failed", speaker_id=speaker.id, error=str(exc))
        return None

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Narrow by first-name match first — cheap, no network calls, and often decisive
    # (surnames collide across generations far more than first names do).
    name_matches = [c for c in candidates if _first_name_matches(c, speaker.name)]
    if len(name_matches) == 1:
        return name_matches[0]
    if name_matches:
        candidates = name_matches

    if not speaker.party_afkorting:
        return None

    matches = [
        c for c in candidates
        if await _resolve_party_membership_match(c["Id"], speaker.party_afkorting)
    ]
    if len(matches) == 1:
        return matches[0]

    logger.info(
        "speaker_persoon_ambiguous",
        speaker_id=speaker.id,
        surname=surname,
        candidate_count=len(candidates),
        party_matches=len(matches),
    )
    return None


async def _save_photo(speaker_id: int, persoon_id: str) -> str | None:
    try:
        data = await download_persoon_photo(persoon_id)
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.warning("speaker_photo_download_failed", speaker_id=speaker_id, error=str(exc))
        return None

    base_path = Path(settings.speaker_images_path)
    base_path.mkdir(parents=True, exist_ok=True)
    file_path = base_path / f"{speaker_id}.jpg"
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(data)
    return str(file_path)


async def enrich_speaker(db: AsyncSession, speaker: Speaker) -> Speaker:
    """
    Best-effort enrichment against the Tweede Kamer OData API.

    Party lookup (by abbreviation) is reliable and always attempted. Person/photo
    lookup is fragile (surnames collide) and may silently fail — the speaker still
    has name/function/party from the stance data either way.
    """
    party_name_nl = speaker.party_name_nl
    party_name_en = speaker.party_name_en
    if speaker.party_afkorting:
        try:
            fractie = await fetch_fractie_by_afkorting(speaker.party_afkorting)
            if fractie:
                party_name_nl = fractie.get("NaamNL")
                party_name_en = fractie.get("NaamEN")
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning("speaker_fractie_lookup_failed", speaker_id=speaker.id, error=str(exc))

    tk_persoon_id = speaker.tk_persoon_id
    image_path = speaker.image_path
    person = await _resolve_person(speaker)
    if person:
        tk_persoon_id = person.get("Id")
        if person.get("ContentType") and person.get("ContentLength") and tk_persoon_id:
            image_path = await _save_photo(speaker.id, tk_persoon_id) or image_path

    repo = SpeakerRepository(db)
    return await repo.update_enrichment(
        speaker,
        party_name_nl=party_name_nl,
        party_name_en=party_name_en,
        tk_persoon_id=tk_persoon_id,
        image_path=image_path,
        resolved_at=datetime.now(timezone.utc),
    )
