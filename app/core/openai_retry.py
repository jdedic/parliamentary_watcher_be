from openai import AsyncOpenAI, RateLimitError
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type


@retry(
    retry=retry_if_exception_type(RateLimitError),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
async def chat_with_retry(client: AsyncOpenAI, **kwargs):
    """Call client.chat.completions.create with exponential backoff on RateLimitError."""
    return await client.chat.completions.create(**kwargs)
