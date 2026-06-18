import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_access import ChatAccessKey
from app.models.chat_eval import ChatEvalRecord


class ChatAccessKeyRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_key(self, key: str) -> ChatAccessKey | None:
        result = await self.db.execute(
            select(ChatAccessKey).where(ChatAccessKey.key == key)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, key_id: int) -> ChatAccessKey | None:
        result = await self.db.execute(
            select(ChatAccessKey).where(ChatAccessKey.id == key_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[ChatAccessKey]:
        result = await self.db.execute(
            select(ChatAccessKey).order_by(ChatAccessKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        label: str | None,
        is_admin: bool,
        max_requests: int | None,
        max_tokens: int | None,
    ) -> ChatAccessKey:
        key_obj = ChatAccessKey(
            key=str(uuid.uuid4()),
            label=label,
            is_admin=is_admin,
            max_requests=max_requests,
            max_tokens=max_tokens,
        )
        self.db.add(key_obj)
        await self.db.flush()
        return key_obj

    async def revoke(self, key_id: int) -> bool:
        result = await self.db.execute(
            delete(ChatAccessKey).where(ChatAccessKey.id == key_id)
        )
        return result.rowcount > 0

    async def get_history(self, key_id: int) -> list[ChatEvalRecord]:
        result = await self.db.execute(
            select(ChatEvalRecord)
            .where(ChatEvalRecord.access_key_id == key_id)
            .order_by(ChatEvalRecord.created_at.desc())
        )
        return list(result.scalars().all())

    async def increment_usage_and_check(
        self,
        key_id: int,
        input_tokens: int,
        output_tokens: int,
    ) -> dict:
        """Atomically increments request and token counters, returns updated state."""
        result = await self.db.execute(
            update(ChatAccessKey)
            .where(ChatAccessKey.id == key_id)
            .values(
                requests_used=ChatAccessKey.requests_used + 1,
                tokens_used=ChatAccessKey.tokens_used + input_tokens + output_tokens,
            )
            .returning(
                ChatAccessKey.requests_used,
                ChatAccessKey.tokens_used,
                ChatAccessKey.max_requests,
                ChatAccessKey.max_tokens,
                ChatAccessKey.is_admin,
            )
        )
        row = result.one()
        return dict(row._mapping)
