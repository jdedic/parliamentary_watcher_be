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
from app.services.translation_service import translate_summary

logger = get_logger(__name__)

# ~50 k tokens — largest observed session is 140 chunks / ~123 k chars; 200 k gives
# headroom above real data while still guarding against corrupted/runaway input.
MAX_SUMMARY_INPUT_CHARS = 200_000

GENERAL_SUMMARY_PROMPT = """You are a parliamentary analyst responsible for producing an accurate and neutral summary of a parliamentary plenary session.
Below are summaries of individual excerpts from a single plenary session.
Write a comprehensive, neutral analytical summary of 300–500 words.
Do not exceed the word limit — it is strictly enforced.

Structure:
- Organise the summary around the main agenda items discussed, in the order they appeared.
- For each agenda item, describe the topic, the key positions taken by speakers, and any notable outcomes or decisions.
- Highlight major interventions and challenges between speakers where relevant.

Neutrality:
- Do not add personal opinions or interpretations.
- Do not favour any speaker or political position.
- Avoid partisan or speculative language.

Antwoord in het Nederlands."""


async def generate_vergadering_summary(vergadering_id: str, db: AsyncSession) -> None:
    validate_guid(vergadering_id)
    repo = PlenarySessionRepository(db)

    status = await repo.get_status(vergadering_id)
    if status != SessionStatus.CHUNK_SUMMARISED:
        logger.info(
            "general_summary_skipped_chunks_not_ready",
            vergadering_id=vergadering_id,
            status=status,
        )
        return

    async with get_vergadering_lock(vergadering_id):
        chunks_path = Path(settings.xml_storage_path) / vergadering_id / "chunks.json"
        if not chunks_path.exists():
            logger.error("chunks_not_found", vergadering_id=vergadering_id)
            return

        chunks = json.loads(chunks_path.read_text(encoding="utf-8"))

        chunk_summaries: list[str] = []
        summary_sources: list[dict] = []
        for chunk in chunks:
            text = chunk.get("summarisation", {}).get("text")
            if text:
                chunk_summaries.append(text)
                summary_sources.append({
                    "chunk_id": chunk.get("chunk_id"),
                    "utterance_ids": (
                        chunk.get("summarisation", {}).get("utterance_ids")
                        or chunk.get("utterance_ids", [])
                    ),
                })

        if not chunk_summaries:
            logger.warning("no_chunk_summaries_found", vergadering_id=vergadering_id)
            return

        # Trim from the tail to stay within the token budget.
        # Earlier chunks anchor the session's agenda order, so we keep the front.
        total_chars = sum(len(s) for s in chunk_summaries)
        if total_chars > MAX_SUMMARY_INPUT_CHARS:
            kept: list[str] = []
            kept_sources: list[dict] = []
            running = 0
            for summary, source in zip(chunk_summaries, summary_sources):
                if running + len(summary) > MAX_SUMMARY_INPUT_CHARS:
                    break
                kept.append(summary)
                kept_sources.append(source)
                running += len(summary)
            logger.warning(
                "chunk_summaries_truncated_for_token_budget",
                vergadering_id=vergadering_id,
                original_count=len(chunk_summaries),
                kept_count=len(kept),
                original_chars=total_chars,
                kept_chars=running,
            )
            chunk_summaries = kept
            summary_sources = kept_sources

        combined_input = "\n\n".join(chunk_summaries)
        logger.info(
            "generating_general_summary",
            vergadering_id=vergadering_id,
            chunk_count=len(chunk_summaries),
        )

        client = AsyncOpenAI(api_key=settings.openai_api_key)

        try:
            response = await chat_with_retry(
                client,
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": GENERAL_SUMMARY_PROMPT},
                    {"role": "user", "content": combined_input},
                ],
            )

            summary_text = response.choices[0].message.content
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens

            logger.info(
                "general_summary_generated",
                vergadering_id=vergadering_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                preview=summary_text[:150],
            )

            await repo.update_summary(
                vergadering_id,
                summary_text,
                SessionStatus.SUMMARISED,
                summary_sources=json.dumps(summary_sources, ensure_ascii=False),
            )
            logger.info(
                "general_summary_saved",
                vergadering_id=vergadering_id,
                status=SessionStatus.SUMMARISED,
            )

            try:
                summary_en = await translate_summary(summary_text)
                await repo.update_summary_en(vergadering_id, summary_en)
                logger.info("summary_translation_saved", vergadering_id=vergadering_id)
            except Exception as e:
                logger.error("summary_translation_failed", vergadering_id=vergadering_id, error=str(e))

        except RateLimitError:
            logger.warning("rate_limit_hit_general_summary", vergadering_id=vergadering_id)
        except APIError as e:
            logger.error("api_error_general_summary", vergadering_id=vergadering_id, error=str(e))
        except Exception as e:
            logger.error("unexpected_error_general_summary", vergadering_id=vergadering_id, error=str(e))
