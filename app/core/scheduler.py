from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.services.session_service import sync_sessions

logger = get_logger(__name__)

_scheduler = AsyncIOScheduler()


async def _run_sync() -> None:
    logger.info("scheduled_sync_started")
    async with AsyncSessionLocal() as db:
        try:
            result = await sync_sessions(db)
            logger.info("scheduled_sync_complete", **result)
        except Exception as exc:
            logger.error("scheduled_sync_failed", error=str(exc))


def start_scheduler(interval_minutes: int) -> None:
    _scheduler.add_job(_run_sync, "interval", minutes=interval_minutes)
    _scheduler.start()
    logger.info("scheduler_started", interval_minutes=interval_minutes)


def stop_scheduler() -> None:
    _scheduler.shutdown(wait=False)
    logger.info("scheduler_stopped")
