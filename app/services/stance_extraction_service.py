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
from app.repositories.plenary_session_repository import PlenarySessionRepository
from app.services.prompt_registry import get_prompt
from app.services.speaker_service import get_or_create_speaker
from app.services.translation_service import translate_stances

logger = get_logger(__name__)

PROCEDURAL_KEYWORDS = ("opening", "sluiting", "stemmingen", "mededelingen", "regeling van werkzaamheden")

_STANCE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "speaker":  {"type": "string"},
        "party":    {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "activity": {"type": "string"},
        "stance":   {"type": "string", "enum": ["support", "oppose", "unclear"]},
        "summary":  {"type": "string"},
        "evidence": {"type": "string"},
    },
    "required": ["speaker", "party", "activity", "stance", "summary", "evidence"],
    "additionalProperties": False,
}

EXTRACTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "stances_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"stances": {"type": "array", "items": _STANCE_ITEM_SCHEMA}},
            "required": ["stances"],
            "additionalProperties": False,
        },
    },
}

RANKING_RESPONSE_FORMAT = EXTRACTION_RESPONSE_FORMAT



def _is_procedural(activity: str) -> bool:
    return any(kw in activity.lower() for kw in PROCEDURAL_KEYWORDS)


def _group_by_activity(utterances: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for u in utterances:
        key = u.get("activity") or "Unknown"
        grouped.setdefault(key, []).append(u)
    return grouped


def _build_speaker_utterance_map(utterances: list[dict]) -> dict[str, list[str]]:
    """Map speaker names (and 'Speaker (Party)' variants) to their utterance_ids."""
    speaker_map: dict[str, list[str]] = {}
    for u in utterances:
        uid = u.get("utterance_id")
        if not uid:
            continue
        speaker = u.get("speaker", "Unknown")
        party = u.get("party")
        speaker_map.setdefault(speaker, []).append(uid)
        if party:
            speaker_map.setdefault(f"{speaker} ({party})", []).append(uid)
    return speaker_map


def _build_activity_input(utterances: list[dict]) -> str:
    lines = []
    for u in utterances:
        speaker = u.get("speaker", "Unknown")
        party = u.get("party")
        label = f"{speaker} ({party})" if party else speaker
        quote = (u.get("quote") or "").strip()
        if quote:
            lines.append(f"[{label}]: {quote}")
    return "\n\n".join(lines)


async def extract_vergadering_stances(vergadering_id: str, db: AsyncSession) -> None:
    validate_guid(vergadering_id)
    transcript_path = Path(settings.xml_storage_path) / vergadering_id / "transcript.json"

    if not transcript_path.exists():
        raise FileNotFoundError(f"transcript.json not found for {vergadering_id}")

    async with get_vergadering_lock(vergadering_id):
        await _do_extract_stances(vergadering_id, db)


async def _do_extract_stances(vergadering_id: str, db: AsyncSession) -> None:
    transcript_path = Path(settings.xml_storage_path) / vergadering_id / "transcript.json"
    if not transcript_path.exists():
        raise FileNotFoundError(f"transcript.json not found for {vergadering_id}")

    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    utterances = transcript.get("utterances", [])
    activities = _group_by_activity(utterances)

    # Filter to debate activities only (>=2 distinct non-chair speakers, non-procedural title)
    debate_activities = {
        name: utts
        for name, utts in activities.items()
        if not _is_procedural(name)
        and len({u["speaker"] for u in utts if not u.get("is_chair")}) >= 2
    }

    logger.info(
        "stance_extraction_started",
        vergadering_id=vergadering_id,
        total_activities=len(activities),
        debate_activities=len(debate_activities),
    )

    if not debate_activities:
        logger.warning("stance_no_debate_activities", vergadering_id=vergadering_id)
        return

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    all_stances: list[dict] = []
    total_input_tokens = 0
    total_output_tokens = 0

    # Pass 1 — extract stances per activity
    for activity_name, activity_utterances in debate_activities.items():
        activity_text = _build_activity_input(activity_utterances)
        if not activity_text.strip():
            continue

        try:
            response = await chat_with_retry(
                client,
                model=settings.openai_model,
                response_format=EXTRACTION_RESPONSE_FORMAT,
                messages=[
                    {"role": "system", "content": get_prompt("stance_extractor")},
                    {"role": "user", "content": f"Activity: {activity_name}\n\n{activity_text}"},
                ],
            )

            raw = response.choices[0].message.content
            parsed = json.loads(raw)
            stances = parsed.get("stances", [])

            speaker_utterance_map = _build_speaker_utterance_map(activity_utterances)
            for stance in stances:
                stance["utterance_ids"] = speaker_utterance_map.get(stance.get("speaker", ""), [])

            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens

            logger.info(
                "stance_activity_extracted",
                vergadering_id=vergadering_id,
                activity=activity_name,
                stances_count=len(stances),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

            all_stances.extend(stances)

        except RateLimitError:
            logger.warning("stance_rate_limit", vergadering_id=vergadering_id, activity=activity_name)
        except (APIError, json.JSONDecodeError) as e:
            logger.error("stance_activity_error", vergadering_id=vergadering_id, activity=activity_name, error=str(e))

    if not all_stances:
        logger.warning("stance_no_stances_extracted", vergadering_id=vergadering_id)
        return

    # Build lookup before ranking so we can restore utterance_ids if the LLM drops them
    stance_uid_index = {
        (s.get("speaker"), s.get("activity")): s.get("utterance_ids", [])
        for s in all_stances
    }

    # Pass 2 — ranking call to select top 10-20
    try:
        ranking_response = await chat_with_retry(
            client,
            model=settings.openai_model,
            response_format=RANKING_RESPONSE_FORMAT,
            messages=[
                {"role": "system", "content": get_prompt("stance_ranker")},
                {"role": "user", "content": json.dumps({"stances": all_stances}, ensure_ascii=False)},
            ],
        )

        raw = ranking_response.choices[0].message.content
        ranked = json.loads(raw)
        final_stances = ranked.get("stances", [])

        rank_input = ranking_response.usage.prompt_tokens
        rank_output = ranking_response.usage.completion_tokens
        total_input_tokens += rank_input
        total_output_tokens += rank_output

        logger.info(
            "stance_ranking_complete",
            vergadering_id=vergadering_id,
            all_stances=len(all_stances),
            selected=len(final_stances),
            input_tokens=rank_input,
            output_tokens=rank_output,
        )

    except (RateLimitError, APIError, json.JSONDecodeError) as e:
        logger.error("stance_ranking_error", vergadering_id=vergadering_id, error=str(e))
        final_stances = all_stances[:20]  # fallback: take first 20 unranked

    # Re-attach utterance_ids if the ranking LLM stripped them
    for stance in final_stances:
        if not stance.get("utterance_ids"):
            stance["utterance_ids"] = stance_uid_index.get(
                (stance.get("speaker"), stance.get("activity")), []
            )

    # Resolve/cache a speaker_id for each stance (DB-only, no network calls here)
    for stance in final_stances:
        speaker_row = await get_or_create_speaker(db, stance.get("speaker"), stance.get("party"))
        stance["speaker_id"] = speaker_row.id if speaker_row else None

    output = json.dumps({
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.openai_model,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "stances": final_stances,
    }, ensure_ascii=False)

    repo = PlenarySessionRepository(db)
    await repo.update_stances(vergadering_id, output)

    logger.info(
        "stance_extraction_saved",
        vergadering_id=vergadering_id,
        final_stances=len(final_stances),
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
    )

    try:
        stances_en = await translate_stances(json.loads(output))
        await repo.update_stances_en(vergadering_id, stances_en)
        logger.info("stances_translation_saved", vergadering_id=vergadering_id)
    except Exception as e:
        logger.error("stances_translation_failed", vergadering_id=vergadering_id, error=str(e))
