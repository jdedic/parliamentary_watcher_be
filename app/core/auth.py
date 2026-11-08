from fastapi import Depends, Request, Security, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.chat_audit import ACCESS_KEY_ID_STATE
from app.core.config import settings
from app.core.database import get_db
from app.models.chat_access import ChatAccessKey

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
CHAT_KEY_HEADER = APIKeyHeader(name="X-Chat-Key", auto_error=False)


async def require_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    """Validate the API key provided in the X-API-Key header."""
    if not api_key or api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return api_key


async def require_chat_key(
    request: Request,
    chat_key: str = Security(CHAT_KEY_HEADER),
    db: AsyncSession = Depends(get_db),
) -> ChatAccessKey | None:
    """
    Validates the X-Chat-Key header against the chat_access_keys table.
    Returns the resolved ChatAccessKey on success, or None when chat_require_key is off.
    Raises 401 if missing or invalid, 403 if the key has exhausted its limits.
    """
    from app.repositories.chat_access_repository import ChatAccessKeyRepository

    if not settings.chat_require_key:
        return None

    if not chat_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing access code. Please enter your access code.",
        )

    repo = ChatAccessKeyRepository(db)
    key_obj = await repo.get_by_key(chat_key)
    if key_obj is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access code. Please contact the administrator for a new one.",
        )

    setattr(request.state, ACCESS_KEY_ID_STATE, key_obj.id)

    if not key_obj.is_admin:
        if key_obj.max_requests is not None and key_obj.requests_used >= key_obj.max_requests:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your access code has expired — you have used all available requests. Please contact the administrator for a new one.",
            )
        if key_obj.max_tokens is not None and key_obj.tokens_used >= key_obj.max_tokens:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your access code has expired — you have used all available tokens. Please contact the administrator for a new one.",
            )

    return key_obj
