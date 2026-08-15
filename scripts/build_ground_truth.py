"""
Build ground-truth relevance labels for eval/ground_truth.json.

For each question in questions.md, retrieves a wide candidate pool (top 25) from Qdrant,
then uses GPT-4.1-mini to judge each (question, chunk) pair for binary relevance.

Run once:
    source venv/bin/activate
    python scripts/build_ground_truth.py

Output: eval/ground_truth.json
Cost: ~$0.03 (10 questions × 25 chunks × ~400 tokens via gpt-4.1-mini)
"""

import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from openai import AsyncOpenAI
from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.core.config import settings
from app.core.logging import setup_logging
from app.services.chat_service import _get_qdrant, _retrieve_for_query, init_clients
from app.services.prompt_registry import load_all_prompts

QUESTIONS_FILE = ROOT / "questions.md"
OUTPUT_FILE = ROOT / "eval" / "ground_truth.json"
CANDIDATE_LIMIT = 25
RELEVANCE_MODEL = "gpt-4.1-mini"


def parse_questions(path: Path) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    session_match = re.search(r"\*\*Session ID:\*\*\s*`([^`]+)`", text)
    session_id = session_match.group(1) if session_match else ""
    questions = re.findall(r"^\d+\.\s+(.+)$", text, re.MULTILINE)
    return session_id, questions


async def judge_relevance(client: AsyncOpenAI, question: str, chunk_text: str) -> bool:
    response = await client.chat.completions.create(
        model=RELEVANCE_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a relevance judge for a Dutch parliamentary Q&A system. "
                    "Given a question and a chunk of transcript text, reply YES if the chunk "
                    "contains information that directly helps answer the question, or NO if it does not. "
                    "Reply with YES or NO only."
                ),
            },
            {
                "role": "user",
                "content": f"Question: {question}\n\nChunk:\n{chunk_text}",
            },
        ],
        temperature=0,
        max_tokens=3,
    )
    answer = response.choices[0].message.content.strip().upper()
    return answer.startswith("YES")


async def build_ground_truth() -> None:
    setup_logging()
    init_clients()
    await load_all_prompts()

    session_id, questions = parse_questions(QUESTIONS_FILE)
    if not session_id or not questions:
        print("ERROR: could not parse questions.md")
        sys.exit(1)

    print(f"Session: {session_id}")
    print(f"Questions: {len(questions)}")
    print(f"Candidate pool per question: {CANDIDATE_LIMIT}\n")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    qdrant = _get_qdrant()
    session_filter = Filter(
        must=[FieldCondition(key="vergadering_id", match=MatchValue(value=session_id))]
    )

    results = []
    total_judgments = 0

    for i, question in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {question[:70]}...")
        candidates = await _retrieve_for_query(
            client, qdrant, session_filter,
            dutch_query=question,
            entity_query="",
            limit=CANDIDATE_LIMIT,
        )

        # Judge all candidates concurrently
        judgments = await asyncio.gather(*[
            judge_relevance(client, question, c["text"])
            for c in candidates
        ])

        relevant_ids = [c["chunk_id"] for c, rel in zip(candidates, judgments) if rel]
        total_judgments += len(candidates)
        print(f"  → {len(relevant_ids)}/{len(candidates)} chunks judged relevant")

        results.append({
            "question": question,
            "session_id": session_id,
            "relevant_chunk_ids": relevant_ids,
            "candidate_chunk_ids": [c["chunk_id"] for c in candidates],
        })

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nDone. {total_judgments} relevance judgments made.")
    print(f"Saved → {OUTPUT_FILE}")

    zero_relevant = [r["question"][:50] for r in results if not r["relevant_chunk_ids"]]
    if zero_relevant:
        print(f"\nWARNING: {len(zero_relevant)} question(s) got 0 relevant chunks:")
        for q in zero_relevant:
            print(f"  - {q}")
        print("Re-run with a larger CANDIDATE_LIMIT (e.g. 40) to expand the pool.")


if __name__ == "__main__":
    asyncio.run(build_ground_truth())
