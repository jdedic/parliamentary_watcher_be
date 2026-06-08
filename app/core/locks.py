import asyncio
from functools import lru_cache

from app.core.utils import validate_guid


@lru_cache(maxsize=1024)
def get_vergadering_lock(vergadering_id: str) -> asyncio.Lock:
    """Return a per-vergadering asyncio.Lock, creating it on first access.

    Prevents concurrent processing of the same vergadering by the background
    scheduler and user-triggered endpoints simultaneously.

    Bounded to 1024 entries via LRU eviction — sufficient for all real
    parliamentary sessions and prevents unbounded growth from arbitrary IDs.
    """
    validate_guid(vergadering_id)
    return asyncio.Lock()
