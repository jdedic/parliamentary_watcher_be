import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from slowapi.errors import RateLimitExceeded

from app.core.limiter import limiter
from app.core.logging import setup_logging, get_logger
from app.core.database import engine, AsyncSessionLocal
from app.core.config import settings
from app.core.scheduler import start_scheduler, stop_scheduler
from app.models import plenary_session  # noqa: F401 — ensures models are registered
from app.models import chat_access  # noqa: F401 — ensures models are registered
from app.api.routes.sessions import router as sessions_router
from app.api.routes.auth import router as auth_router
from app.services.session_service import sync_sessions
from app.services.chat_service import init_clients, close_clients, _get_qdrant

logger = get_logger(__name__)


async def _run_startup_sync() -> None:
    async with AsyncSessionLocal() as db:
        try:
            summary = await sync_sessions(db)
            logger.info("Startup sync finished", **summary)
        except RuntimeError as exc:
            logger.error("Startup sync failed — external API unavailable", reason=str(exc))
        except Exception as exc:
            logger.error("Unexpected error during startup sync", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    On startup:
      - Initialises logging.
      - Fires the session sync pipeline as a background task so the server
        starts accepting requests immediately (existing sessions are available
        right away while new ones are processed in the background).

    On shutdown:
      - Disposes the database engine.
    """
    setup_logging()
    logger.info("Parliamentary Summary API starting up")

    init_clients()
    asyncio.create_task(_run_startup_sync())
    start_scheduler(settings.sync_interval_minutes)

    yield

    stop_scheduler()
    await close_clients()
    logger.info("Parliamentary Summary API shutting down")
    await engine.dispose()


app = FastAPI(
    title="Parliamentary Summary API",
    description="Fetches, stores, and serves Tweede Kamer plenary session data.",
    version="0.1.0",
    lifespan=lifespan,
)

def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"You have exceeded the chat rate limit ({exc.limit}). Please wait a moment before sending another message."},
    )

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-API-Key"],
)

app.include_router(sessions_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")


async def _check_db() -> str:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        logger.error("health_check_db_failed", error=str(exc))
        return "unreachable"


async def _check_qdrant() -> str:
    try:
        await _get_qdrant().get_collections()
        return "ok"
    except Exception as exc:
        logger.error("health_check_qdrant_failed", error=str(exc))
        return "unreachable"


@app.get("/health", tags=["Health"])
async def health_check() -> JSONResponse:
    """Liveness + readiness check — verifies DB and Qdrant are reachable."""
    db_status, qdrant_status = await asyncio.gather(_check_db(), _check_qdrant())
    checks = {"db": db_status, "qdrant": qdrant_status}
    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )
