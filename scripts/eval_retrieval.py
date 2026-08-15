"""
Retrieval eval: compare pipeline with vs without reranking.

Computes Recall@1/3/5, MRR, nDCG@5 for both variants against the ground truth
in eval/ground_truth.json.  Optionally runs generate_with_judge for answer quality.

Usage:
    source venv/bin/activate
    python scripts/eval_retrieval.py              # retrieval metrics only
    python scripts/eval_retrieval.py --judge      # + answer quality (costs API tokens)
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.metrics import ndcg_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from openai import AsyncOpenAI
from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.core.config import settings
from app.core.logging import setup_logging
from app.services.chat_service import (
    _get_qdrant,
    _preprocess_query,
    _rerank_chunks,
    _retrieve_for_query,
    init_clients,
)
from app.services.judge_service import generate_with_judge
from app.services.prompt_registry import load_all_prompts

GROUND_TRUTH_FILE = ROOT / "eval" / "ground_truth.json"
RESULTS_DIR = ROOT / "eval"
EVAL_LIMIT = 10  # candidates to rank (production uses 5; wider is fairer for Recall@5)
MAX_CONTEXT_CHARS = 6000


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def recall_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    hits = sum(1 for cid in ranked_ids[:k] if cid in relevant_ids)
    return hits / len(relevant_ids)


def mrr(ranked_ids: list[str], relevant_ids: set[str]) -> float:
    for rank, cid in enumerate(ranked_ids, 1):
        if cid in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        return 0.0
    relevance = [1 if cid in relevant_ids else 0 for cid in ranked_ids[:k]]
    ideal = sorted(relevance, reverse=True)
    # pad to k
    relevance += [0] * (k - len(relevance))
    ideal += [0] * (k - len(ideal))
    return ndcg_score([ideal], [relevance])


def aggregate(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

async def run_eval(run_judge: bool) -> None:
    setup_logging()
    init_clients()
    await load_all_prompts()

    if not GROUND_TRUTH_FILE.exists():
        print(f"ERROR: {GROUND_TRUTH_FILE} not found. Run build_ground_truth.py first.")
        sys.exit(1)

    ground_truth = json.loads(GROUND_TRUTH_FILE.read_text(encoding="utf-8"))
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    qdrant = _get_qdrant()

    metrics_a: dict[str, list[float]] = {"r1": [], "r3": [], "r5": [], "mrr": [], "ndcg5": []}
    metrics_b: dict[str, list[float]] = {"r1": [], "r3": [], "r5": [], "mrr": [], "ndcg5": []}
    judge_a: list[str] = []
    judge_b: list[str] = []
    per_question = []

    print(f"Evaluating {len(ground_truth)} questions ...\n")

    for entry in ground_truth:
        question = entry["question"]
        session_id = entry["session_id"]
        relevant = set(entry["relevant_chunk_ids"])

        if not relevant:
            print(f"  SKIP (no relevant chunks): {question[:60]}")
            continue

        print(f"  Q: {question[:70]}")

        # Preprocess → Dutch query
        preprocessed = await _preprocess_query(client, question)
        dutch_query = preprocessed.get("query_nl") or question
        entity_query = preprocessed.get("entity_query", "")

        session_filter = Filter(
            must=[FieldCondition(key="vergadering_id", match=MatchValue(value=session_id))]
        )

        # Retrieve candidate pool (same pool for both variants = fair comparison)
        candidates = await _retrieve_for_query(
            client, qdrant, session_filter,
            dutch_query=dutch_query,
            entity_query=entity_query,
            limit=EVAL_LIMIT,
        )

        # Variant A: RRF order (already sorted by score desc from _retrieve_for_query)
        ranked_a = [c["chunk_id"] for c in candidates]

        # Variant B: CrossEncoder rerank order
        reranked = await _rerank_chunks(dutch_query, [dict(c) for c in candidates])
        ranked_b = [c["chunk_id"] for c in reranked]

        # Retrieval metrics
        for k, key in [(1, "r1"), (3, "r3"), (5, "r5")]:
            metrics_a[key].append(recall_at_k(ranked_a, relevant, k))
            metrics_b[key].append(recall_at_k(ranked_b, relevant, k))
        metrics_a["mrr"].append(mrr(ranked_a, relevant))
        metrics_b["mrr"].append(mrr(ranked_b, relevant))
        metrics_a["ndcg5"].append(ndcg_at_k(ranked_a, relevant, 5))
        metrics_b["ndcg5"].append(ndcg_at_k(ranked_b, relevant, 5))

        row = {
            "question": question,
            "relevant_count": len(relevant),
            "a_r1": metrics_a["r1"][-1], "a_r3": metrics_a["r3"][-1], "a_r5": metrics_a["r5"][-1],
            "a_mrr": metrics_a["mrr"][-1], "a_ndcg5": metrics_a["ndcg5"][-1],
            "b_r1": metrics_b["r1"][-1], "b_r3": metrics_b["r3"][-1], "b_r5": metrics_b["r5"][-1],
            "b_mrr": metrics_b["mrr"][-1], "b_ndcg5": metrics_b["ndcg5"][-1],
        }

        # Optional answer quality
        if run_judge:
            for label, ranked in [("a", ranked_a), ("b", ranked_b)]:
                top_chunks = [c for c in candidates if c["chunk_id"] in ranked[:5]]
                context = "\n\n---\n\n".join(c["text"] for c in top_chunks)[:MAX_CONTEXT_CHARS]
                messages = [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": question},
                ]
                _, judge_result, _ = await generate_with_judge(
                    client, messages, context, question, settings.openai_generation_model
                )
                verdict = judge_result.get("verdict", "needs_review")
                if label == "a":
                    judge_a.append(verdict)
                    row["a_verdict"] = verdict
                else:
                    judge_b.append(verdict)
                    row["b_verdict"] = verdict

        per_question.append(row)

        a_r5 = metrics_a["r5"][-1]
        b_r5 = metrics_b["r5"][-1]
        print(f"    Recall@5 → no-rerank: {a_r5:.2f}  rerank: {b_r5:.2f}  relevant: {len(relevant)}")

    # Aggregate
    def agg(m: dict) -> dict:
        return {k: aggregate(v) for k, v in m.items()}

    agg_a = agg(metrics_a)
    agg_b = agg(metrics_b)
    n = len(per_question)

    # Print comparison table
    print(f"\n{'─' * 52}")
    print(f"{'Metric':<16} {'No rerank':>10} {'Rerank':>10} {'Δ':>10}")
    print(f"{'─' * 52}")
    for label, key in [("Recall@1", "r1"), ("Recall@3", "r3"), ("Recall@5", "r5"), ("MRR", "mrr"), ("nDCG@5", "ndcg5")]:
        a, b = agg_a[key], agg_b[key]
        delta = round(b - a, 3)
        sign = "+" if delta >= 0 else ""
        print(f"{label:<16} {a:>10.3f} {b:>10.3f} {sign + str(delta):>10}")
    if run_judge and judge_a and judge_b:
        pass_a = round(judge_a.count("pass") / len(judge_a) * 100, 1)
        pass_b = round(judge_b.count("pass") / len(judge_b) * 100, 1)
        delta = round(pass_b - pass_a, 1)
        sign = "+" if delta >= 0 else ""
        print(f"{'Judge pass%':<16} {pass_a:>9.1f}% {pass_b:>9.1f}% {sign + str(delta) + '%':>10}")
    print(f"{'─' * 52}")
    print(f"Questions evaluated: {n}\n")

    # Save results
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out = {
        "timestamp": timestamp,
        "questions_evaluated": n,
        "aggregate": {"no_rerank": agg_a, "rerank": agg_b},
        "per_question": per_question,
    }
    result_path = RESULTS_DIR / f"results_{timestamp}.json"
    result_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Results saved → {result_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge", action="store_true", help="Also run generate+judge for answer quality")
    args = parser.parse_args()
    asyncio.run(run_eval(args.judge))
