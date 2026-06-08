import json
import uuid
from pathlib import Path

import nltk
from nltk.tokenize import sent_tokenize

from app.core.config import settings
from app.core.logging import get_logger
from app.core.utils import validate_guid

logger = get_logger(__name__)

EMBED_MIN_WORDS = 300
EMBED_MAX_WORDS = 500
OVERLAP_SENTENCES = 2  # sentences carried into next chunk as overlap


def _word_count(text: str) -> int:
    return len(text.split())


def _sentences(text: str) -> list[str]:
    """Split text into sentences using NLTK punkt tokenizer (Dutch-aware)."""
    return sent_tokenize(text, language="dutch")


def _sentences_to_text(sentences: list[str]) -> str:
    return " ".join(s.strip() for s in sentences if s.strip())


def _group_into_exchanges(utterances: list[dict]) -> list[list[dict]]:
    """Group utterances into exchanges: main turn + following interruptions."""
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
    grouped: dict[str, list[dict]] = {}
    for utterance in utterances:
        key = utterance.get("activity") or ""
        grouped.setdefault(key, []).append(utterance)
    return grouped


def _split_exchange_by_sentences(
    exchange_sentences: list[str],
    utterance_meta: list[dict],
    vergadering: dict,
    overlap_sentences: list[str],
) -> list[dict]:
    """
    Split an oversized exchange into sentence-aware sub-chunks.
    Each sub-chunk starts with overlap sentences from the previous sub-chunk.
    """
    sub_chunks = []
    current_sentences: list[str] = list(overlap_sentences)

    for sentence in exchange_sentences:
        current_sentences.append(sentence)

        if _word_count(_sentences_to_text(current_sentences)) >= EMBED_MAX_WORDS:
            # Flush before this sentence would push us over — if we're already over,
            # flush including it (single very long sentence edge case)
            flush_sentences = current_sentences
            sub_chunks.append({
                "chunk_id": str(uuid.uuid4()),
                "vergadering": vergadering,
                "utterances": utterance_meta,
                "word_count": _word_count(_sentences_to_text(flush_sentences)),
                "text": _sentences_to_text(flush_sentences),
            })
            # Carry last OVERLAP_SENTENCES into next sub-chunk
            current_sentences = current_sentences[-OVERLAP_SENTENCES:]

    # Flush remaining
    if current_sentences and _sentences_to_text(current_sentences).strip():
        sub_chunks.append({
            "chunk_id": str(uuid.uuid4()),
            "vergadering": vergadering,
            "utterances": utterance_meta,
            "word_count": _word_count(_sentences_to_text(current_sentences)),
            "text": _sentences_to_text(current_sentences),
        })

    return sub_chunks


def build_embedding_chunks(vergadering_id: str) -> Path:
    """
    Read transcript.json and produce chunks_embeddings.json optimised for
    vector search.

    Strategy:
    - Utterances grouped by activity (no cross-topic chunks).
    - Within each activity, utterances grouped into exchanges (main turn +
      interruptions keep question/answer together).
    - Chunks target 300–500 words, split and accumulated on sentence boundaries
      using NLTK punkt tokenizer (Dutch).
    - OVERLAP_SENTENCES sentences are carried from the end of each chunk into
      the beginning of the next, preserving context across boundaries.
    - Each chunk carries rich metadata: vergadering (id, title, date range) and
      per-utterance metadata (utterance_id, speaker, party, is_chair).

    Args:
        vergadering_id: UUID of the vergadering.

    Returns:
        Path to the written chunks_embeddings.json file.

    Raises:
        FileNotFoundError: If transcript.json does not exist.
    """
    validate_guid(vergadering_id)
    vergadering_dir = Path(settings.xml_storage_path) / vergadering_id
    transcript_path = vergadering_dir / "transcript.json"

    if not transcript_path.exists():
        raise FileNotFoundError(f"transcript.json not found: {transcript_path}")

    logger.info("embedding_chunks_started", vergadering_id=vergadering_id)

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))

    vergadering = {
        "id": transcript.get("vergadering_id"),
        "title": transcript.get("title"),
        "start_date": transcript.get("date"),
        "end_date": transcript.get("end_date"),
    }

    utterances = transcript.get("utterances", [])
    chunks: list[dict] = []

    # Rolling accumulator
    acc_sentences: list[str] = []
    acc_utterances: list[dict] = []  # utterance metadata objects
    overlap_sentences: list[str] = []

    def flush(carry_overlap: bool) -> None:
        nonlocal acc_sentences, acc_utterances, overlap_sentences
        if not acc_sentences:
            return
        text = _sentences_to_text(acc_sentences)
        if not text.strip():
            return
        chunks.append({
            "chunk_id": str(uuid.uuid4()),
            "vergadering": vergadering,
            "utterances": acc_utterances[:],
            "word_count": _word_count(text),
            "text": text,
        })
        if carry_overlap:
            overlap_sentences = acc_sentences[-OVERLAP_SENTENCES:]
            acc_sentences = list(overlap_sentences)
            acc_utterances = []
        else:
            overlap_sentences = []
            acc_sentences = []
            acc_utterances = []

    activities = _group_by_activity(utterances)

    for activity_utterances in activities.values():
        exchanges = _group_into_exchanges(activity_utterances)

        for exchange in exchanges:
            # Build exchange text and per-utterance metadata
            exchange_sentences: list[str] = []
            exchange_meta: list[dict] = []

            for u in exchange:
                quote = (u.get("quote") or "").strip()
                if not quote:
                    continue
                exchange_sentences.extend(_sentences(quote))
                exchange_meta.append({
                    "utterance_id": u.get("utterance_id"),
                    "speaker": u.get("speaker"),
                    "party": u.get("party"),
                    "is_chair": u.get("is_chair", False),
                })

            if not exchange_sentences:
                continue

            exchange_text = _sentences_to_text(exchange_sentences)
            exchange_wc = _word_count(exchange_text)

            # Oversized exchange — flush accumulator, then split the exchange
            if exchange_wc > EMBED_MAX_WORDS:
                logger.debug(
                    "embedding_chunk_oversized_exchange",
                    vergadering_id=vergadering_id,
                    word_count=exchange_wc,
                    speakers=[u.get("speaker") for u in exchange_meta],
                )
                flush(carry_overlap=False)
                sub_chunks = _split_exchange_by_sentences(
                    exchange_sentences,
                    exchange_meta,
                    vergadering,
                    overlap_sentences,
                )
                chunks.extend(sub_chunks)
                # Seed overlap from tail of last sub-chunk
                if sub_chunks:
                    last_text = sub_chunks[-1]["text"]
                    overlap_sentences = _sentences(last_text)[-OVERLAP_SENTENCES:]
                    acc_sentences = list(overlap_sentences)
                    acc_utterances = []
                continue

            # Adding this exchange would exceed max — flush first
            if acc_sentences and _word_count(_sentences_to_text(acc_sentences)) + exchange_wc > EMBED_MAX_WORDS:
                flush(carry_overlap=True)

            acc_sentences.extend(exchange_sentences)
            acc_utterances.extend(exchange_meta)

            # Reached target range — flush
            if _word_count(_sentences_to_text(acc_sentences)) >= EMBED_MIN_WORDS:
                flush(carry_overlap=True)

        # Activity boundary — flush without overlap (no cross-topic context)
        flush(carry_overlap=False)

    for i, chunk in enumerate(chunks):
        chunk["chunk_index"] = i

    output_path = vergadering_dir / "chunks_embeddings.json"
    output_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2))

    logger.info(
        "embedding_chunks_written",
        vergadering_id=vergadering_id,
        chunks=len(chunks),
        utterances=len(utterances),
        path=str(output_path),
    )

    return output_path
