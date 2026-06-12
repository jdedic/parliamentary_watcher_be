import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.chat_eval import ChatEvalRecord

logger = get_logger(__name__)

COST_PER_TOKEN: dict[str, dict[str, float]] = {
    "gpt-4.1":      {"input": 2.00 / 1_000_000, "output": 8.00 / 1_000_000},
    "gpt-4.1-mini": {"input": 0.40 / 1_000_000, "output": 1.60 / 1_000_000},
    "gpt-4o":       {"input": 2.50 / 1_000_000, "output": 10.00 / 1_000_000},
}


def _compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = COST_PER_TOKEN.get(model, {"input": 0.0, "output": 0.0})
    return round(rates["input"] * input_tokens + rates["output"] * output_tokens, 6)


def _resolve_run_id() -> str:
    return settings.eval_run_id or f"live_{datetime.now(timezone.utc).strftime('%Y%m%d')}"


def _write_entry(log_path: Path, entry: dict) -> None:
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_accuracy_pct() -> float | None:
    log_path = Path(settings.xml_storage_path).parent / "chat_eval.jsonl"
    if not log_path.exists():
        return None
    total, passed = 0, 0
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("_summary"):
                continue
            total += 1
            if row.get("judge_verdict") == "pass":
                passed += 1
    return round(passed / total * 100, 1) if total else None


async def log_chat_response(
    session_id: str,
    question: str,
    answer: str,
    retrieval_confidence: str,
    generation_confidence: str,
    judge_verdict: str,
    judge_result: dict,
    matched_speakers: list[str],
    context_chunk_ids: list[str],
    retrieved_chunk_ids: list[str],
    regenerated: bool,
    model: str,
    latency_ms: int,
    input_tokens: int,
    output_tokens: int,
) -> None:
    entry = {
        "run_id": _resolve_run_id(),
        "question_id": uuid.uuid4().hex[:8],
        "session_id": session_id,
        "question": question,
        "answer": answer,
        "context_chunk_ids": context_chunk_ids,
        "retrieved_chunk_ids": retrieved_chunk_ids,
        "matched_speakers": matched_speakers,
        "retrieval_confidence": retrieval_confidence,
        "generation_confidence": generation_confidence,
        "judge_verdict": judge_verdict,
        "judge": {
            "grounded": judge_result.get("grounded"),
            "answers_question": judge_result.get("answers_question"),
            "missing_context": judge_result.get("missing_context"),
            "missing_parts": judge_result.get("missing_parts", []),
            "unsupported_claims": judge_result.get("unsupported_claims", []),
            "entity_errors": judge_result.get("entity_errors", []),
            "reason": judge_result.get("reason", ""),
        },
        "regenerated": regenerated,
        "model": model,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_estimate_usd": _compute_cost(model, input_tokens, output_tokens),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    log_path = Path(settings.xml_storage_path).parent / "chat_eval.jsonl"
    try:
        await asyncio.to_thread(_write_entry, log_path, entry)
    except Exception as exc:
        logger.warning("eval_log_write_failed", error=str(exc))

    try:
        judge = entry["judge"]
        async with AsyncSessionLocal() as db:
            db.add(ChatEvalRecord(
                question_id=entry["question_id"],
                run_id=entry["run_id"],
                session_id=entry["session_id"],
                question=entry["question"],
                answer=entry["answer"],
                retrieval_confidence=entry["retrieval_confidence"],
                generation_confidence=entry["generation_confidence"],
                judge_verdict=entry["judge_verdict"],
                judge_grounded=judge.get("grounded"),
                judge_answers_question=judge.get("answers_question"),
                judge_missing_context=judge.get("missing_context"),
                judge_missing_parts=judge.get("missing_parts", []),
                judge_unsupported_claims=judge.get("unsupported_claims", []),
                judge_entity_errors=judge.get("entity_errors", []),
                judge_reason=judge.get("reason"),
                context_chunk_ids=entry["context_chunk_ids"],
                retrieved_chunk_ids=entry["retrieved_chunk_ids"],
                matched_speakers=entry["matched_speakers"],
                regenerated=entry["regenerated"],
                model=entry["model"],
                latency_ms=entry["latency_ms"],
                input_tokens=entry["input_tokens"],
                output_tokens=entry["output_tokens"],
                cost_estimate_usd=entry["cost_estimate_usd"],
            ))
            await db.commit()
    except Exception as exc:
        logger.warning("eval_db_write_failed", error=str(exc))
