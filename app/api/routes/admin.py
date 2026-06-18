from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key
from app.core.database import get_db
from app.core.logging import get_logger
from app.repositories.chat_access_repository import ChatAccessKeyRepository
from app.schemas.chat_access import CreateKeyRequest, KeyHistoryEntry, KeyHistoryResponse, KeyListResponse, KeyResponse

router = APIRouter(prefix="/admin/keys", tags=["Admin"])

logger = get_logger(__name__)


@router.post("", response_model=KeyResponse, status_code=201, summary="Create a chat access key")
async def create_key(
    body: CreateKeyRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> KeyResponse:
    try:
        repo = ChatAccessKeyRepository(db)
        key_obj = await repo.create(
            label=body.label,
            is_admin=body.is_admin,
            max_requests=body.max_requests,
            max_tokens=body.max_tokens,
        )
        await db.commit()
        await db.refresh(key_obj)
        return KeyResponse.model_validate(key_obj)
    except Exception as exc:
        logger.error("create_key_failed", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create access key.",
        )


@router.get("", response_model=KeyListResponse, summary="List all chat access keys")
async def list_keys(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> KeyListResponse:
    try:
        repo = ChatAccessKeyRepository(db)
        keys = await repo.list_all()
        from app.schemas.chat_access import KeyListItem
        return KeyListResponse(
            keys=[KeyListItem.model_validate(k) for k in keys],
            total=len(keys),
        )
    except Exception as exc:
        logger.error("list_keys_failed", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve access keys.",
        )


@router.get("/{key_id}/history", response_model=KeyHistoryResponse, summary="Get chat history for a key")
async def get_key_history(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> KeyHistoryResponse:
    try:
        repo = ChatAccessKeyRepository(db)
        key_obj = await repo.get_by_id(key_id)
        if key_obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Access key not found.",
            )
        records = await repo.get_history(key_id)
        return KeyHistoryResponse(
            key_id=key_id,
            label=key_obj.label,
            entries=[KeyHistoryEntry.model_validate(r) for r in records],
            total=len(records),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("get_key_history_failed", key_id=key_id, error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve chat history.",
        )


@router.delete("/{key_id}", status_code=204, summary="Revoke a chat access key")
async def revoke_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> None:
    try:
        repo = ChatAccessKeyRepository(db)
        deleted = await repo.revoke(key_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Access key not found.",
            )
        await db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("revoke_key_failed", key_id=key_id, error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke access key.",
        )
