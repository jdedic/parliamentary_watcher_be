from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.plenary_session import PlenarySession, PlenarySessionDocument, SessionStatus


class PlenarySessionRepository:
    """Handles all database operations for PlenarySession."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        title: str | None = None,
        meeting_number: int | None = None,
        status: SessionStatus | None = None,
        is_final: bool | None = None,
    ) -> tuple[int, list[PlenarySession]]:
        """
        Retrieve paginated list of sessions with their documents.

        Returns:
            Tuple of (total_count, sessions).
        """
        filters = []
        if title is not None:
            filters.append(PlenarySession.title.ilike(f"%{title}%"))
        if meeting_number is not None:
            filters.append(PlenarySession.meeting_number == meeting_number)
        if status is not None:
            filters.append(PlenarySession.status == status)
        if is_final is not None:
            filters.append(PlenarySession.is_final.is_(is_final))

        count_result = await self.db.execute(
            select(func.count()).select_from(PlenarySession).where(*filters)
        )
        total = count_result.scalar_one()

        result = await self.db.execute(
            select(PlenarySession)
            .options(selectinload(PlenarySession.documents))
            .where(*filters)
            .order_by(PlenarySession.date.desc().nullslast())
            .offset(skip)
            .limit(limit)
        )
        sessions = list(result.scalars().all())
        return total, sessions

    async def get_by_id(self, session_id: str) -> PlenarySession | None:
        """Retrieve a single session by its ID, including documents."""
        result = await self.db.execute(
            select(PlenarySession)
            .options(selectinload(PlenarySession.documents))
            .where(PlenarySession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def exists(self, session_id: str) -> bool:
        """Check whether a session already exists in the database."""
        result = await self.db.execute(
            select(func.count())
            .select_from(PlenarySession)
            .where(PlenarySession.id == session_id)
        )
        return result.scalar_one() > 0

    async def get_non_final_ids(self) -> list[str]:
        """Return ids of all sessions not yet backed by an Eindpublicatie."""
        result = await self.db.execute(
            select(PlenarySession.id).where(PlenarySession.is_final.is_(False))
        )
        return list(result.scalars().all())

    async def upsert(self, session: PlenarySession) -> PlenarySession:
        """
        Insert a new session or skip if it already exists.

        Returns:
            The persisted PlenarySession instance.
        """
        existing = await self.get_by_id(session.id)
        if existing:
            return existing

        self.db.add(session)
        await self.db.flush()
        return session

    async def document_exists(self, document_id: str) -> bool:
        """Check whether a document has already been downloaded and recorded."""
        result = await self.db.execute(
            select(func.count())
            .select_from(PlenarySessionDocument)
            .where(PlenarySessionDocument.document_id == document_id)
        )
        return result.scalar_one() > 0

    async def add_document(
        self, doc: PlenarySessionDocument
    ) -> PlenarySessionDocument:
        """Persist a new session document record."""
        self.db.add(doc)
        await self.db.flush()
        return doc

    async def update_status(self, session_id: str, status: SessionStatus) -> None:
        """Update the download status of a session."""
        session = await self.get_by_id(session_id)
        if session:
            session.status = status
            await self.db.flush()

    async def update_publication_state(
        self, session_id: str, current_verslag_id: str, is_final: bool
    ) -> None:
        """Record which verslag currently backs a session's content, and its finality."""
        session = await self.get_by_id(session_id)
        if session:
            session.current_verslag_id = current_verslag_id
            session.is_final = is_final
            await self.db.flush()

    async def update_chair(self, session_id: str, chair: str) -> None:
        """Update the chair name of a session."""
        session = await self.get_by_id(session_id)
        if session:
            session.chair = chair
            await self.db.flush()

    async def get_status(self, session_id: str) -> SessionStatus | None:
        """Return the current status of a session."""
        result = await self.db.execute(
            select(PlenarySession.status).where(PlenarySession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def update_summary(
        self,
        session_id: str,
        summary: str,
        status: SessionStatus,
        summary_sources: str | None = None,
    ) -> None:
        """Save the general summary, its source references, and update status."""
        session = await self.get_by_id(session_id)
        if session:
            session.summary = summary
            session.status = status
            session.summary_sources = summary_sources
            await self.db.flush()

    async def update_stances(self, session_id: str, stances: str) -> None:
        """Save the extracted speaker stances as a JSON string."""
        session = await self.get_by_id(session_id)
        if session:
            session.stances = stances
            await self.db.flush()

    async def update_summary_en(self, session_id: str, summary_en: str) -> None:
        """Save the English translation of the session summary."""
        session = await self.get_by_id(session_id)
        if session:
            session.summary_en = summary_en
            await self.db.flush()

    async def update_stances_en(self, session_id: str, stances_en: str) -> None:
        """Save the English translation of the stances as a JSON string."""
        session = await self.get_by_id(session_id)
        if session:
            session.stances_en = stances_en
            await self.db.flush()
