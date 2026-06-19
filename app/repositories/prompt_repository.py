from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt_version import PromptVersion


class PromptRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all_active(self) -> list[PromptVersion]:
        result = await self.db.execute(
            select(PromptVersion).where(PromptVersion.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def get_all_names(self) -> list[PromptVersion]:
        """Return the active version row for each distinct prompt name."""
        result = await self.db.execute(
            select(PromptVersion)
            .where(PromptVersion.is_active.is_(True))
            .order_by(PromptVersion.name)
        )
        return list(result.scalars().all())

    async def get_versions_for_name(self, name: str) -> list[PromptVersion]:
        result = await self.db.execute(
            select(PromptVersion)
            .where(PromptVersion.name == name)
            .order_by(PromptVersion.version.desc())
        )
        return list(result.scalars().all())

    async def get_by_name_and_version(self, name: str, version: int) -> PromptVersion | None:
        result = await self.db.execute(
            select(PromptVersion).where(
                PromptVersion.name == name,
                PromptVersion.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def get_next_version_number(self, name: str) -> int:
        result = await self.db.execute(
            select(PromptVersion.version)
            .where(PromptVersion.name == name)
            .order_by(PromptVersion.version.desc())
            .limit(1)
        )
        current = result.scalar_one_or_none()
        return (current or 0) + 1

    async def create(self, name: str, content: str) -> PromptVersion:
        version = await self.get_next_version_number(name)
        pv = PromptVersion(name=name, version=version, content=content, is_active=False)
        self.db.add(pv)
        await self.db.flush()
        return pv

    async def activate(self, name: str, version: int) -> PromptVersion | None:
        await self.db.execute(
            update(PromptVersion)
            .where(PromptVersion.name == name)
            .values(is_active=False)
        )
        await self.db.execute(
            update(PromptVersion)
            .where(PromptVersion.name == name, PromptVersion.version == version)
            .values(is_active=True)
        )
        return await self.get_by_name_and_version(name, version)
