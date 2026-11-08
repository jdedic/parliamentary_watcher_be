from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.chat_audit import ACCESS_KEY_ID_STATE
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.repositories.chat_access_repository import ChatAccessKeyRepository
from app.schemas.chat_auth import ChatAuthRequest

router = APIRouter(prefix="/auth", tags=["Auth"])

logger = get_logger(__name__)


@router.post("/chat", status_code=200, summary="Verify chat access code")
async def verify_chat_password(
    request: Request,
    body: ChatAuthRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not settings.chat_require_key:
        return {"authenticated": True, "requests_remaining": None, "tokens_remaining": None}

    try:
        repo = ChatAccessKeyRepository(db)
        key_obj = await repo.get_by_key(body.password)
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

        return {
            "authenticated": True,
            "requests_remaining": (
                key_obj.max_requests - key_obj.requests_used
                if key_obj.max_requests is not None else None
            ),
            "tokens_remaining": (
                key_obj.max_tokens - key_obj.tokens_used
                if key_obj.max_tokens is not None else None
            ),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("verify_chat_password_failed", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify access code.",
        )
