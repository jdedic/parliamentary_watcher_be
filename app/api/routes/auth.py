from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.chat_access import ChatAccessKey
from app.schemas.chat_auth import ChatAuthRequest

router = APIRouter(prefix="/auth", tags=["Auth"])

logger = get_logger(__name__)


@router.post("/chat", status_code=200, summary="Verify chat access code")
async def verify_chat_password(
    body: ChatAuthRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    try:
        result = await db.execute(
            select(ChatAccessKey).where(ChatAccessKey.key == body.password)
        )
        key = result.scalar_one_or_none()
        if key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access code",
            )
        return {"authenticated": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("verify_chat_password_failed", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify access code.",
        )
