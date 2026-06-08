import copy
import json

from openai import AsyncOpenAI, RateLimitError, APIError

from app.core.config import settings
from app.core.logging import get_logger
from app.core.openai_retry import chat_with_retry

logger = get_logger(__name__)

SUMMARY_TRANSLATION_PROMPT = """You are a professional translator specialising in Dutch parliamentary texts.
Translate the following Dutch parliamentary session summary into clear, fluent English.
Preserve all proper nouns (names of people, parties, institutions) exactly as written.
Do not add or remove content — this is a direct translation only."""

STANCES_TRANSLATION_PROMPT = """You are a professional translator specialising in Dutch parliamentary texts.
Translate the following Dutch text into clear, fluent English.
Preserve all proper nouns (names of people, parties, institutions) exactly as written.
Return only the translated text, nothing else."""


async def translate_summary(dutch_text: str) -> str:
    """Translate a Dutch session summary to English using gpt-4.1-mini."""
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        response = await chat_with_retry(
            client,
            model=settings.openai_model,
            max_tokens=1200,
            messages=[
                {"role": "system", "content": SUMMARY_TRANSLATION_PROMPT},
                {"role": "user", "content": dutch_text},
            ],
        )
        return response.choices[0].message.content
    except (RateLimitError, APIError) as e:
        logger.error("summary_translation_failed", error=str(e))
        raise


async def translate_stances(stances_data: dict) -> str:
    """
    Translate summary and activity fields in each stance to English.

    Returns a JSON string with the same structure as stances_data but with
    stance.summary and stance.activity translated. Evidence and speaker fields
    are left unchanged (verbatim quotes and proper nouns).
    """
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    translated = copy.deepcopy(stances_data)

    for stance in translated.get("stances", []):
        for field in ("summary", "activity"):
            dutch_text = stance.get(field)
            if not dutch_text:
                continue
            try:
                response = await chat_with_retry(
                    client,
                    model=settings.openai_model,
                    max_tokens=300,
                    messages=[
                        {"role": "system", "content": STANCES_TRANSLATION_PROMPT},
                        {"role": "user", "content": dutch_text},
                    ],
                )
                stance[field] = response.choices[0].message.content
            except (RateLimitError, APIError) as e:
                logger.error("stance_field_translation_failed", field=field, error=str(e))

    return json.dumps(translated, ensure_ascii=False)
