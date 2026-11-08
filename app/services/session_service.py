import os
import httpx
from pathlib import Path
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.core.http_client import (
    fetch_vergadering_list,
    fetch_vergaderingen_with_latest_verslag,
    fetch_verslag_list_raw,
    pick_current_verslag,
    download_verslag_xml,
)
from app.core.utils import to_iso, to_int, validate_guid
from app.models.plenary_session import PlenarySession, PlenarySessionDocument, SessionStatus
from app.repositories.plenary_session_repository import PlenarySessionRepository
from app.schemas.plenary_session import SessionListResponse, PlenarySessionSchema
from app.services.transcript_service import build_transcript
from app.services.chunking_service import build_chunks
from app.services.embedding_chunks_service import build_embedding_chunks
from app.services.embedding_service import generate_embeddings
from app.services.summarisation_service import summarise_vergadering
from app.services.vergadering_summary_service import generate_vergadering_summary
from app.services.stance_extraction_service import extract_vergadering_stances

logger = get_logger(__name__)


def _map_item_to_model(item: dict) -> PlenarySession:
    """Map a raw API response item to a PlenarySession ORM model."""
    return PlenarySession(
        id=item.get("Id"),
        kind=item.get("Soort"),
        title=item.get("Titel"),
        room=item.get("Zaal"),
        parliamentary_year=item.get("Vergaderjaar"),
        meeting_number=to_int(item.get("VergaderingNummer")),
        date=to_iso(item.get("Datum")),
        start_time=to_iso(item.get("Aanvangstijd")),
        end_time=to_iso(item.get("Sluiting")),
        chamber=item.get("Kamer"),
        modified_at=to_iso(item.get("GewijzigdOp")),
        api_modified_at=to_iso(item.get("ApiGewijzigdOp")),
        deleted=bool(item.get("Verwijderd", False)),
    )


async def _process_current_verslag(
    session_id: str,
    current_verslag: dict,
    repo: PlenarySessionRepository,
) -> tuple[bool, bool, bool]:
    """
    Download the session's current-best verslag if it's new.

    Deliberately does NOT update the session's publication state (current_verslag_id/
    is_final) — that only happens once the full pipeline has successfully reprocessed
    the session (see sync_sessions, Step 5). Marking it "current" any earlier would mean
    a mid-pipeline failure silently looks like success on the next sync: content_changed
    would come back False even though summary/stances were never actually saved for
    this revision, and the session would never be retried.

    Returns (downloaded_new_document, content_changed, download_failed).
    content_changed is True when this verslag differs from what the session was
    previously tracking (a new Tussenpublicatie revision, or promotion to
    Eindpublicatie) — i.e. the full pipeline needs to (re-)run.
    """
    doc_id = current_verslag.get("Id")
    if not doc_id:
        return False, False, False

    session = await repo.get_by_id(session_id)
    content_changed = session is None or session.current_verslag_id != doc_id

    downloaded_new_document = False
    if not await repo.document_exists(doc_id):
        try:
            xml_bytes = await download_verslag_xml(verslag_id=doc_id)
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.error(
                "Failed to download XML for verslag",
                document_id=doc_id,
                session_id=session_id,
                error=str(exc),
            )
            return False, False, True

        file_path = _save_xml(session_id=session_id, doc_id=doc_id, data=xml_bytes)
        doc = PlenarySessionDocument(
            session_id=session_id,
            document_id=doc_id,
            kind=current_verslag.get("Soort"),
            file_path=file_path,
        )
        await repo.add_document(doc)
        downloaded_new_document = True
        logger.info(
            "XML downloaded and saved",
            session_id=session_id,
            document_id=doc_id,
            is_final=current_verslag["is_final"],
            file_path=file_path,
        )

    return downloaded_new_document, content_changed, False


async def sync_sessions(db: AsyncSession) -> dict:
    """
    Full sync pipeline:
      1. Discover vergaderingen with a usable verslag (Tussenpublicatie or
         Eindpublicatie) and persist any new sessions.
      2. Re-check already-tracked non-final sessions directly, in case a newer
         Tussenpublicatie or the Eindpublicatie has since appeared.
      3. Download the current verslag XML for any session whose content changed.
      4. Re-run the full pipeline (transcript → chunks → embeddings → summary →
         stances) only for sessions whose content actually changed this run.

    Args:
        db: Active async database session.

    Returns:
        Summary dict with counts of new sessions and documents.
    """
    repo = PlenarySessionRepository(db)
    new_sessions = 0
    new_documents = 0
    failed_sessions = 0
    failed_documents = 0

    # --- Step 1: Discover vergaderingen with a usable verslag ---
    logger.info(
        "Starting session sync — collecting vergaderingen with a usable verslag",
        limit=settings.sync_limit,
        batch_size=settings.sync_batch_size,
    )
    try:
        discovered = await fetch_vergaderingen_with_latest_verslag(
            limit=settings.sync_limit,
            batch_size=settings.sync_batch_size,
        )
    except httpx.RequestError as exc:
        logger.error(
            "Cannot reach Tweede Kamer API — network error",
            error=str(exc),
        )
        raise RuntimeError(
            "External API is unreachable. Please check your network connection."
        ) from exc
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Tweede Kamer API returned an error response",
            status_code=exc.response.status_code,
        )
        raise RuntimeError(
            f"External API responded with HTTP {exc.response.status_code}."
        ) from exc

    logger.info("Fetched vergaderingen with usable verslag", count=len(discovered))

    # --- Step 2: Persist newly discovered sessions ---
    sessions_to_process: dict[str, dict] = {}
    for item in discovered:
        session_id = item.get("Id")
        if not session_id:
            logger.warning("Skipping item with missing Id", item=item)
            continue

        try:
            is_new = not await repo.exists(session_id)
            model = _map_item_to_model(item)
            await repo.upsert(model)
            if is_new:
                new_sessions += 1
                logger.info("New session saved", session_id=session_id, titel=item.get("Titel"))
        except Exception as exc:
            failed_sessions += 1
            logger.error("Failed to persist session", session_id=session_id, error=str(exc))
            continue

        sessions_to_process[session_id] = item["current_verslag"]

    await db.commit()

    # --- Step 3: Re-check already-tracked non-final sessions not seen above ---
    pending_ids = await repo.get_non_final_ids()
    for session_id in pending_ids:
        if session_id in sessions_to_process:
            continue
        try:
            verslag_raw = await fetch_verslag_list_raw(session_id)
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            logger.error("Failed to re-check pending session", session_id=session_id, error=str(exc))
            continue

        current_verslag = pick_current_verslag(verslag_raw.get("value", []))
        if current_verslag:
            sessions_to_process[session_id] = current_verslag

    # --- Step 4: Download current verslag (if new) + update publication state ---
    sessions_needing_reprocess: list[str] = []
    for session_id, current_verslag in sessions_to_process.items():
        downloaded, content_changed, download_failed = await _process_current_verslag(
            session_id, current_verslag, repo
        )
        if download_failed:
            failed_documents += 1
        if downloaded:
            new_documents += 1
        if content_changed:
            sessions_needing_reprocess.append(session_id)

    await db.commit()

    # --- Step 5: Re-run the full pipeline only for sessions whose content changed ---
    for session_id in sessions_needing_reprocess:
        try:
            # Parse XML → transcript.json (utterances, speaker, party, activity, timestamps)
            _, chair_name = await build_transcript(session_id)
            if chair_name:
                await repo.update_chair(session_id, chair_name)
            # Split transcript into 800-1200 word exchange-based chunks → chunks.json
            await build_chunks(session_id)
            # Build sentence-aware 300-500 word chunks for vector search → chunks_embeddings.json
            await build_embedding_chunks(session_id)
            # Embed chunks and upsert into Qdrant (plenary_chunks collection) — replaces
            # any previously-embedded revision of this session (see generate_embeddings).
            await generate_embeddings(session_id)
            logger.info("embeddings_generated", session_id=session_id)
            await repo.update_status(session_id, SessionStatus.DOWNLOADED)

            # Step 1 of 2 summarisation: summarise each chunk individually (map step).
            # Writes 3-5 sentence summary per chunk back into chunks.json.
            # Sets status CHUNK_SUMMARISED when all chunks are done.
            await summarise_vergadering(session_id, db)
            logger.info("summarised_session", session_id=session_id)

            # Extract top 10-20 speaker stances per key topic from transcript.json
            await extract_vergadering_stances(session_id, db)

            # Step 2 of 2 summarisation: combine all chunk summaries into one 300-500 word
            # general session summary (reduce step). Saves to DB, sets status SUMMARISED.
            await generate_vergadering_summary(session_id, db)

            # Only now mark this verslag as "current" — after every step above has
            # actually succeeded and been flushed, so a mid-pipeline failure leaves
            # content_changed True (and thus gets retried) on the next sync instead
            # of being silently treated as already handled.
            current_verslag = sessions_to_process[session_id]
            await repo.update_publication_state(
                session_id,
                current_verslag_id=current_verslag["Id"],
                is_final=current_verslag["is_final"],
            )
        except (FileNotFoundError, ValueError) as exc:
            logger.debug("Skipping transcript build", session_id=session_id, reason=str(exc))
        except Exception as exc:
            logger.error("Failed to build transcript or chunks", session_id=session_id, error=str(exc))
            # A failed flush leaves the session's transaction unusable — without this,
            # every subsequent session in this run would fail too (PendingRollbackError),
            # turning one bad session into a cascading failure across the whole batch.
            await db.rollback()

    await db.commit()

    summary = {
        "new_sessions": new_sessions,
        "new_documents": new_documents,
        "failed_sessions": failed_sessions,
        "failed_documents": failed_documents,
        "total_fetched": len(discovered),
        "reprocessed": len(sessions_needing_reprocess),
    }
    logger.info("Session sync complete", **summary)
    return summary


async def list_sessions(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    title: str | None = None,
    meeting_number: int | None = None,
) -> SessionListResponse:
    repo = PlenarySessionRepository(db)
    total, sessions = await repo.get_all(
        skip=skip,
        limit=limit,
        title=title,
        meeting_number=meeting_number,
    )
    return SessionListResponse(
        total=total,
        sessions=[PlenarySessionSchema.model_validate(s) for s in sessions],
    )


def _save_xml(session_id: str, doc_id: str, data: bytes) -> str:
    """
    Save XML bytes to the filesystem under storage/xml_files/{session_id}/.

    Args:
        session_id: Parent session GUID (used as folder name).
        doc_id: Document GUID (used as filename).
        data: Raw XML bytes to write.

    Returns:
        Relative file path as string.
    """
    validate_guid(session_id)
    validate_guid(doc_id)
    base_path = Path(settings.xml_storage_path) / session_id
    base_path.mkdir(parents=True, exist_ok=True)
    file_path = base_path / f"{doc_id}.xml"
    file_path.write_bytes(data)
    return str(file_path)

async def get_session_by_id(db: AsyncSession, session_id: str) -> PlenarySession | None:
    """Retrieve a single session by its ID."""
    repo = PlenarySessionRepository(db)
    session = await repo.get_by_id(session_id)
    if session is None:
        logger.warning("Session not found", session_id=session_id)
    return session


class SessionService:
    """Service class for session queries, injected into routes via FastAPI Depends."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.repo = PlenarySessionRepository(db)

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        title: str | None = None,
        meeting_number: int | None = None,
        status: SessionStatus | None = None,
        is_final: bool | None = None,
    ) -> SessionListResponse:
        total, sessions = await self.repo.get_all(
            skip=skip, limit=limit, title=title, meeting_number=meeting_number, status=status, is_final=is_final
        )
        return SessionListResponse(
            total=total,
            sessions=[PlenarySessionSchema.model_validate(s) for s in sessions],
        )

    async def get_by_id(self, session_id: str) -> PlenarySession | None:
        session = await self.repo.get_by_id(session_id)
        if session is None:
            logger.warning("Session not found", session_id=session_id)
        return session