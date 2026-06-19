from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.repositories.prompt_repository import PromptRepository

logger = get_logger(__name__)

_cache: dict[str, dict] = {}  # name -> {"content": str, "version": int}


def get_prompt(name: str, **kwargs) -> str:
    """Return the active prompt content, filling any {placeholders} with kwargs."""
    entry = _cache.get(name)
    if entry is None:
        raise KeyError(f"Prompt '{name}' not found — ensure load_all_prompts() ran at startup")
    content = entry["content"]
    return content.format(**kwargs) if kwargs else content


def get_version_label(name: str) -> str:
    """Return a version string like 'rag_assistant@v2' for eval tracking."""
    entry = _cache.get(name)
    return f"{name}@v{entry['version']}" if entry else "unknown"


async def load_all_prompts() -> None:
    async with AsyncSessionLocal() as db:
        repo = PromptRepository(db)
        active = await repo.get_all_active()
    _cache.clear()
    for pv in active:
        _cache[pv.name] = {"content": pv.content, "version": pv.version}
    logger.info("prompts_loaded", count=len(_cache), names=sorted(_cache.keys()))


async def reload_prompts() -> None:
    await load_all_prompts()
    logger.info("prompts_reloaded", count=len(_cache))
