import asyncio
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
    fetch_vergaderings_with_eindpublicatie,
    fetch_verslag_list_raw,
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


async def sync_sessions(db: AsyncSession) -> dict:
    """
    Full sync pipeline:
      1. Fetch all sessions from Tweede Kamer API.
      2. Persist new sessions to the database.
      3. For each session, fetch and download associated XML documents.

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

    # --- Step 1: Fetch vergaderings that have an Eindpublicatie ---
    logger.info(
        "Starting session sync — collecting vergaderings with Eindpublicatie",
        limit=settings.sync_limit,
        batch_size=settings.sync_batch_size,
    )
    try:
        items = await fetch_vergaderings_with_eindpublicatie(
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

    logger.info("Fetched sessions with Eindpublicatie", count=len(items))

    # --- Step 2: Persist new sessions ---
    for item in items:
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

        # --- Step 3: Download XMLs — verslagen already fetched in Step 1 ---
        verslagen: list[dict] = item.get("verslagen", [])
        if not verslagen:
            await repo.update_status(session_id, SessionStatus.FAILED)
            logger.warning("No XML documents found for session, marked FAILED", session_id=session_id)
            continue

        for verslag in verslagen:
            doc_id = verslag.get("Id")
            if not doc_id:
                continue

            already_exists = await repo.document_exists(doc_id)
            if already_exists:
                logger.debug("Document already downloaded, skipping", document_id=doc_id)
                continue

            # Download XML bytes
            try:
                xml_bytes = await download_verslag_xml(verslag_id=doc_id)
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                failed_documents += 1
                logger.error(
                    "Failed to download XML for verslag",
                    document_id=doc_id,
                    error=str(exc),
                )
                continue

            # Save XML to filesystem
            file_path = _save_xml(session_id=session_id, doc_id=doc_id, data=xml_bytes)

            # Record in database
            doc = PlenarySessionDocument(
                session_id=session_id,
                document_id=doc_id,
                file_path=file_path,
            )
            await repo.add_document(doc)
            new_documents += 1
            logger.info(
                "XML downloaded and saved",
                session_id=session_id,
                document_id=doc_id,
                file_path=file_path,
            )

    await db.commit()

    # --- Step 4: Build transcript JSON for each session that has XML files ---
    processed_sessions = [item.get("Id") for item in items if item.get("Id")]
    for session_id in processed_sessions:
        try:
            current_status = await repo.get_status(session_id)

            if current_status in (SessionStatus.CHUNK_SUMMARISED, SessionStatus.SUMMARISED):
                logger.info(
                    "session_already_processed_skipping",
                    session_id=session_id,
                    status=current_status,
                )
                continue

            if current_status != SessionStatus.DOWNLOADED:
                # Parse XML → transcript.json (utterances, speaker, party, activity, timestamps)
                loop = asyncio.get_event_loop()
                _, chair_name = await loop.run_in_executor(None, build_transcript, session_id)
                if chair_name:
                    await repo.update_chair(session_id, chair_name)
                # Split transcript into 800-1200 word exchange-based chunks → chunks.json
                await loop.run_in_executor(None, build_chunks, session_id)
                # Build sentence-aware 300-500 word chunks for vector search → chunks_embeddings.json
                await loop.run_in_executor(None, build_embedding_chunks, session_id)
                # Embed chunks and upsert into Qdrant (plenary_chunks collection)
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
            # Triggered manually via POST /sessions/{id}/summarise endpoint.
            await generate_vergadering_summary(session_id, db)
        except (FileNotFoundError, ValueError) as exc:
            logger.debug("Skipping transcript build", session_id=session_id, reason=str(exc))
        except Exception as exc:
            logger.error("Failed to build transcript or chunks", session_id=session_id, error=str(exc))

    await db.commit()

    summary = {
        "new_sessions": new_sessions,
        "new_documents": new_documents,
        "failed_sessions": failed_sessions,
        "failed_documents": failed_documents,
        "total_fetched": len(items),
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
    ) -> SessionListResponse:
        total, sessions = await self.repo.get_all(
            skip=skip, limit=limit, title=title, meeting_number=meeting_number, status=status
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