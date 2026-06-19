import json

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import get_logger
from app.services.prompt_registry import get_prompt

logger = get_logger(__name__)

_FALLBACK_JUDGE = {
    "verdict": "needs_review",
    "grounded": True,
    "answers_question": True,
    "missing_parts": [],
    "unsupported_claims": [],
    "entity_errors": [],
    "missing_context": False,
    "confidence": "low",
    "reason": "Judge parse failure — returning answer unverified",
}


def _empty_usage() -> dict:
    return {"input_tokens": 0, "output_tokens": 0}


def _add_usage(acc: dict, response) -> None:
    if response.usage:
        acc["input_tokens"] += response.usage.prompt_tokens
        acc["output_tokens"] += response.usage.completion_tokens


async def judge_answer(
    client: AsyncOpenAI,
    question: str,
    context: str,
    answer: str,
) -> tuple[dict, dict]:
    """Judge whether the answer is grounded in the provided context.
    Returns (judge_result, usage).
    """
    usage = _empty_usage()
    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": get_prompt("answer_quality_judge")},
                {"role": "user", "content": (
                    f"Question:\n{question}\n\n"
                    f"Retrieved excerpts:\n{context}\n\n"
                    f"Generated answer:\n{answer}"
                )},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=600,
        )
        _add_usage(usage, response)
        result = json.loads(response.choices[0].message.content)
        logger.info(
            "judge_result",
            verdict=result.get("verdict"),
            grounded=result.get("grounded"),
            missing_context=result.get("missing_context"),
            confidence=result.get("confidence"),
            reason=result.get("reason"),
        )
        return result, usage
    except Exception as exc:
        logger.warning("judge_failed", error=str(exc))
        return _FALLBACK_JUDGE.copy(), usage


async def generate_with_judge(
    client: AsyncOpenAI,
    messages: list[dict],
    judge_context: str,
    question: str,
    model: str,
) -> tuple[str, dict, dict]:
    """
    Generate an answer, judge it against a wider context, regenerate once on fail.
    Returns (final_answer, judge_result, usage).
    """
    usage = _empty_usage()

    # First generation
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=1024,
        temperature=0.3,
    )
    _add_usage(usage, response)
    answer = response.choices[0].message.content

    # Judge using wider context (top 10 chunks)
    judge, judge_usage = await judge_answer(client, question, judge_context, answer)
    usage["input_tokens"] += judge_usage["input_tokens"]
    usage["output_tokens"] += judge_usage["output_tokens"]
    verdict = judge.get("verdict", "needs_review")

    if verdict == "pass":
        return answer, judge, usage

    if verdict == "needs_review":
        missing_parts = judge.get("missing_parts", [])
        if not judge.get("answers_question", True) and missing_parts and not judge.get("missing_context"):
            suffix = (
                "\nA grounding evaluator found that your previous answer was incomplete. "
                "The following parts of the question were not addressed:\n"
                f"{missing_parts}\n\n"
                "Please provide a complete answer that covers all parts of the question. "
                "Base your answer only on the provided excerpts."
            )
            regen_messages = messages[:-1] + [{
                "role": "user",
                "content": messages[-1]["content"] + "\n\n" + suffix,
            }]
            logger.info("judge_triggering_completion", missing_parts=missing_parts)
            regen_response = await client.chat.completions.create(
                model=model,
                messages=regen_messages,
                max_tokens=1024,
                temperature=0.3,
            )
            _add_usage(usage, regen_response)
            regen_answer = regen_response.choices[0].message.content
            regen_judge, regen_judge_usage = await judge_answer(client, question, judge_context, regen_answer)
            usage["input_tokens"] += regen_judge_usage["input_tokens"]
            usage["output_tokens"] += regen_judge_usage["output_tokens"]
            regen_judge["_regenerated"] = True
            return regen_answer, regen_judge, usage
        judge["confidence"] = "low"
        return answer, judge, usage

    # verdict == "fail"
    if judge.get("missing_context"):
        judge["confidence"] = "low"
        return answer, judge, usage

    # Regenerate once with judge findings injected into the user message
    suffix = (
        "\nThe previous answer had the following issues identified by a grounding evaluator:\n"
        f"Unsupported claims: {judge.get('unsupported_claims', [])}\n"
        f"Entity errors: {judge.get('entity_errors', [])}\n\n"
        "Regenerate the answer strictly avoiding these issues. "
        "Base your answer only on the provided excerpts."
    )
    regen_messages = messages[:-1] + [{
        "role": "user",
        "content": messages[-1]["content"] + "\n\n" + suffix,
    }]
    logger.info("judge_triggering_regeneration", verdict=verdict)

    regen_response = await client.chat.completions.create(
        model=model,
        messages=regen_messages,
        max_tokens=1024,
        temperature=0.3,
    )
    _add_usage(usage, regen_response)
    regen_answer = regen_response.choices[0].message.content

    regen_judge, regen_judge_usage = await judge_answer(client, question, judge_context, regen_answer)
    usage["input_tokens"] += regen_judge_usage["input_tokens"]
    usage["output_tokens"] += regen_judge_usage["output_tokens"]
    regen_judge["_regenerated"] = True
    return regen_answer, regen_judge, usage
