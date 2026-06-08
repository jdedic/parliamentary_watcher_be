import json
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.core.utils import validate_guid

logger = get_logger(__name__)

CHUNK_MIN_WORDS = 800
CHUNK_MAX_WORDS = 1200
OVERLAP_WORDS = 50


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _word_count(text: str) -> int:
    return len(text.split())


def _split_into_subchunks(text: str, utterance_ids: list[str], vergadering_meta: dict) -> list[dict]:
    """
    Split an oversized text block into sub-chunks with OVERLAP_WORDS overlap.
    Used when a single exchange exceeds CHUNK_MAX_WORDS.
    """
    words = text.split()
    subchunks = []
    start = 0

    while start < len(words):
        end = start + CHUNK_MAX_WORDS
        chunk_words = words[start:end]
        subchunks.append({
            "chunk_id": str(uuid.uuid4()),
            **vergadering_meta,
            "utterance_ids": utterance_ids[:],
            "word_count": len(chunk_words),
            "text": " ".join(chunk_words),
        })
        if end >= len(words):
            break
        start = end - OVERLAP_WORDS

    return subchunks


def _flush_chunk(
    accumulated_words: list[str],
    utterance_ids: list[str],
    vergadering_meta: dict,
) -> dict:
    return {
        "chunk_id": str(uuid.uuid4()),
        **vergadering_meta,
        "utterance_ids": utterance_ids[:],
        "word_count": len(accumulated_words),
        "text": " ".join(accumulated_words),
    }


def _group_into_exchanges(utterances: list[dict]) -> list[list[dict]]:
    """
    Group utterances into exchanges within a single activity.

    An exchange starts with a non-interruption utterance (a new top-level
    speaker turn) and collects all following interruptions as part of that
    same exchange. Chair utterances are excluded entirely.

    Example:
        [Member A speaks]         <- starts exchange 1
        [Minister interrupts]     <- part of exchange 1
        [Member A replies]        <- part of exchange 1
        [Member B speaks]         <- starts exchange 2
    """
    exchanges: list[list[dict]] = []
    current: list[dict] = []

    for utterance in utterances:
        if not utterance.get("is_interruption"):
            if current:
                exchanges.append(current)
            current = [utterance]
        else:
            current.append(utterance)

    if current:
        exchanges.append(current)

    return exchanges


def _group_by_activity(utterances: list[dict]) -> dict[str, list[dict]]:
    """
    Partition utterances by their activity field, preserving order.
    Utterances with no activity are grouped under an empty-string key.
    """
    grouped: dict[str, list[dict]] = {}
    for utterance in utterances:
        key = utterance.get("activity") or ""
        grouped.setdefault(key, []).append(utterance)
    return grouped


# ---------------------------------------------------------------------------
# Public service function
# ---------------------------------------------------------------------------


def build_chunks(vergadering_id: str) -> Path:
    """
    Read transcript.json for a vergadering, chunk the utterance quotes,
    and write chunks.json to the same directory.

    Chunking strategy:
    - Utterances are first grouped by activity (debate topic), so chunks
      never span two different topics.
    - Within each activity, utterances are grouped into exchanges: a
      top-level speaker turn plus all interruptions that follow it.
      This keeps questions and their answers in the same chunk.
    - Exchanges are accumulated into chunks of 800–1200 words.
    - A 50-word overlap is carried into the next chunk when flushing,
      preserving conversational context across chunk boundaries.
    - If a single exchange exceeds 1200 words it is split into sub-chunks
      with 50-word overlap.
    - Chair utterances (procedural) are excluded throughout.

    Args:
        vergadering_id: UUID of the vergadering (subdirectory under xml_storage_path).

    Returns:
        Path to the written chunks.json file.

    Raises:
        FileNotFoundError: If transcript.json does not exist.
    """
    validate_guid(vergadering_id)
    vergadering_dir = Path(settings.xml_storage_path) / vergadering_id
    transcript_path = vergadering_dir / "transcript.json"

    if not transcript_path.exists():
        raise FileNotFoundError(f"transcript.json not found: {transcript_path}")

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))

    vergadering_meta = {
        "vergadering_id": transcript.get("vergadering_id"),
        "title": transcript.get("title"),
        "date": transcript.get("date"),
        "parliamentary_year": transcript.get("parliamentary_year"),
        "meeting_number": transcript.get("meeting_number"),
    }

    utterances = transcript.get("utterances", [])
    chunks: list[dict] = []

    # Rolling accumulator — shared across exchanges within one activity
    accumulated_words: list[str] = []
    accumulated_ids: list[str] = []

    def flush(carry_overlap: bool) -> None:
        nonlocal accumulated_words, accumulated_ids
        if not accumulated_words:
            return
        chunks.append(_flush_chunk(accumulated_words, accumulated_ids, vergadering_meta))
        if carry_overlap:
            accumulated_words = accumulated_words[-OVERLAP_WORDS:]
            accumulated_ids = []
        else:
            accumulated_words = []
            accumulated_ids = []

    activities = _group_by_activity(utterances)

    for activity_utterances in activities.values():
        exchanges = _group_into_exchanges(activity_utterances)

        for exchange in exchanges:
            exchange_text = " ".join(
                (u.get("quote") or "").strip()
                for u in exchange
                if (u.get("quote") or "").strip()
            )
            exchange_ids = [u["utterance_id"] for u in exchange if u.get("utterance_id")]
            exchange_wc = _word_count(exchange_text)

            if not exchange_text:
                continue

            # Oversized exchange — flush current accumulator, then split exchange
            if exchange_wc > CHUNK_MAX_WORDS:
                flush(carry_overlap=False)
                sub_chunks = _split_into_subchunks(exchange_text, exchange_ids, vergadering_meta)
                chunks.extend(sub_chunks)
                # Seed overlap from the tail of the last sub-chunk
                if sub_chunks:
                    accumulated_words = sub_chunks[-1]["text"].split()[-OVERLAP_WORDS:]
                    accumulated_ids = []
                continue

            # Adding this exchange would exceed max — always flush regardless of min.
            # CHUNK_MAX_WORDS is a hard limit; CHUNK_MIN_WORDS is only a soft target.
            if accumulated_words and len(accumulated_words) + exchange_wc > CHUNK_MAX_WORDS:
                flush(carry_overlap=True)

            accumulated_words.extend(exchange_text.split())
            accumulated_ids.extend(exchange_ids)

            # Hit target range — flush with overlap
            if len(accumulated_words) >= CHUNK_MIN_WORDS:
                flush(carry_overlap=True)

        # Activity boundary — flush cleanly, no overlap across topics
        flush(carry_overlap=False)

    output_path = vergadering_dir / "chunks.json"
    output_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2))

    logger.info(
        "Chunks written",
        vergadering_id=vergadering_id,
        chunks=len(chunks),
        path=str(output_path),
    )

    return output_path
