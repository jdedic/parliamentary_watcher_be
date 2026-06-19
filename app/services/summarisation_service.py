import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from openai import AsyncOpenAI, RateLimitError, APIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.locks import get_vergadering_lock
from app.core.logging import get_logger
from app.core.openai_retry import chat_with_retry
from app.core.utils import validate_guid
from app.models.plenary_session import SessionStatus
from app.repositories.plenary_session_repository import PlenarySessionRepository
from app.services.prompt_registry import get_prompt

logger = get_logger(__name__)

BATCH_SIZE = 3


async def _summarise_chunk(client: AsyncOpenAI, chunk: dict) -> None:
    """Summarise a single chunk in-place, retrying once on rate limit."""
    chunk_id = chunk.get("chunk_id")
    logger.info("summarising_chunk", chunk_id=chunk_id, word_count=chunk.get("word_count"))

    try:
        response = await chat_with_retry(
            client,
            model=settings.openai_model,
            max_tokens=400,
            messages=[
                {"role": "system", "content": get_prompt("chunk_summariser")},
                {"role": "user", "content": chunk["text"]},
            ],
        )

        summary_text = response.choices[0].message.content
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens

        logger.info(
            "chunk_summarised",
            chunk_id=chunk_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            preview=summary_text[:100],
        )

        chunk["summarisation"] = {
            "text": summary_text,
            "model": settings.openai_model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "summarised_at": datetime.now(timezone.utc).isoformat(),
            "utterance_ids": chunk.get("utterance_ids", []),
        }

    except RateLimitError:
        logger.warning("rate_limit_exhausted", chunk_id=chunk_id)
    except APIError as e:
        logger.error("api_error", chunk_id=chunk_id, error=str(e))
    except Exception as e:
        logger.error("unexpected_error", chunk_id=chunk_id, error=str(e))


async def summarise_vergadering(vergadering_id: str, db: AsyncSession) -> None:
    validate_guid(vergadering_id)
    repo = PlenarySessionRepository(db)

    status = await repo.get_status(vergadering_id)
    if status in (SessionStatus.CHUNK_SUMMARISED, SessionStatus.SUMMARISED):
        logger.info(
            "chunk_summarisation_skipped_already_done",
            vergadering_id=vergadering_id,
            status=status,
        )
        return

    async with get_vergadering_lock(vergadering_id):
        await _do_summarise(vergadering_id, db)


async def _do_summarise(vergadering_id: str, db: AsyncSession) -> None:
    repo = PlenarySessionRepository(db)
    chunks_path = Path(settings.xml_storage_path) / vergadering_id / "chunks.json"
    if not chunks_path.exists():
        logger.error("chunks_not_found", vergadering_id=vergadering_id, path=str(chunks_path))
        return

    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    pending = [c for c in chunks if not c.get("summarisation")]
    skipped = len(chunks) - len(pending)

    logger.info(
        "summarisation_started",
        vergadering_id=vergadering_id,
        total=len(chunks),
        pending=len(pending),
        skipped=skipped,
        batch_size=BATCH_SIZE,
    )

    # Process in batches of BATCH_SIZE concurrently
    for batch_start in range(0, len(pending), BATCH_SIZE):
        batch = pending[batch_start: batch_start + BATCH_SIZE]
        logger.info(
            "summarisation_batch_started",
            vergadering_id=vergadering_id,
            batch_start=batch_start,
            batch_size=len(batch),
        )
        await asyncio.gather(*[_summarise_chunk(client, chunk) for chunk in batch])
        logger.info(
            "summarisation_batch_complete",
            vergadering_id=vergadering_id,
            batch_start=batch_start,
        )

    chunks_path.write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summarised = sum(1 for c in chunks if c.get("summarisation"))
    all_summarised = summarised == len(chunks)

    if all_summarised:
        await repo.update_status(vergadering_id, SessionStatus.CHUNK_SUMMARISED)
        logger.info(
            "all_chunks_summarised_status_updated",
            vergadering_id=vergadering_id,
            status=SessionStatus.CHUNK_SUMMARISED,
        )
    else:
        logger.warning(
            "some_chunks_failed_not_marking_chunk_summarised",
            vergadering_id=vergadering_id,
            summarised=summarised,
            total=len(chunks),
        )

    logger.info(
        "summarisation_complete",
        vergadering_id=vergadering_id,
        summarised=summarised,
        skipped=skipped,
        total=len(chunks),
    )
