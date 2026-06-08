from fastapi import APIRouter, Depends, Query, HTTPException, Request, status

from app.core.auth import require_api_key
from app.core.database import get_db
from app.core.limiter import limiter
from app.core.logging import get_logger
from app.models.plenary_session import SessionStatus
from app.core.config import settings
from app.schemas.plenary_session import SessionListResponse, PlenarySessionSchema, ChatRequest, ChatResponse
from app.services.session_service import SessionService
from app.services.vergadering_summary_service import generate_vergadering_summary
from app.services.embedding_chunks_service import build_embedding_chunks
from app.services.embedding_service import generate_embeddings
from app.services.stance_extraction_service import extract_vergadering_stances
from app.services.chat_service import chat_about_session
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/sessions", tags=["Sessions"])

logger = get_logger(__name__)


@router.get(
    "",
    response_model=SessionListResponse,
    summary="List plenary sessions",
    description="Returns all plenary sessions stored in the local database. Requires API key authentication.",
)
async def get_sessions(
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=1, le=500, description="Max records to return"),
    title: str | None = Query(default=None, description="Filter by title (case-insensitive substring match)"),
    meeting_number: int | None = Query(default=None, description="Filter by meeting number (exact match)"),
    status_filter: SessionStatus | None = Query(default=None, alias="status", description="Filter by session status"),
    service: SessionService = Depends(),
    _: str = Depends(require_api_key),
) -> SessionListResponse:
    try:
        return await service.list(skip=skip, limit=limit, title=title, meeting_number=meeting_number, status=status_filter)
    except Exception as exc:
        logger.error("list_sessions_failed", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve sessions.",
        )


@router.get("/{session_id}", response_model=PlenarySessionSchema, summary="Get session by ID")
async def get_session(
    session_id: str,
    service: SessionService = Depends(),
    _: str = Depends(require_api_key),
) -> PlenarySessionSchema:
    session = await service.get_by_id(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return PlenarySessionSchema.model_validate(session)


@router.post(
    "/{session_id}/summarise",
    summary="Generate general summary for a vergadering",
    description="Triggers general summary generation from chunk summaries for the given vergadering ID.",
)
async def summarise_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    try:
        await generate_vergadering_summary(session_id, db)
        await db.commit()
        return {"status": "ok", "vergadering_id": session_id}
    except Exception as exc:
        logger.error("summarise_session_failed", session_id=session_id, error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate summary.",
        )


@router.post(
    "/{session_id}/createEmbeddingsChunks",
    summary="Build embedding chunks for a vergadering",
    description="Splits the transcript into sentence-aware 300–500 word chunks optimised for vector search and writes chunks_embeddings.json.",
)
async def create_embedding_chunks(
    session_id: str,
    _: str = Depends(require_api_key),
) -> dict:
    try:
        build_embedding_chunks(session_id)
        return {"status": "ok", "vergadering_id": session_id}
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session data not found.")
    except Exception as exc:
        logger.error("create_embedding_chunks_failed", session_id=session_id, error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to build embedding chunks.",
        )


@router.post(
    "/{session_id}/extractStances",
    summary="Extract speaker stances for a vergadering",
    description="Reads transcript.json, extracts per-speaker stances per activity, ranks to top 10-20, and saves to DB.",
)
async def extract_session_stances(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> dict:
    try:
        await extract_vergadering_stances(session_id, db)
        await db.commit()
        return {"status": "ok", "vergadering_id": session_id}
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session data not found.")
    except Exception as exc:
        logger.error("extract_stances_failed", session_id=session_id, error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to extract stances.",
        )


@router.post("/{session_id}/chat", response_model=ChatResponse, summary="Chat about a session")
@limiter.limit(settings.chat_rate_limit)
async def chat_session(
    request: Request,
    session_id: str,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> ChatResponse:
    try:
        result = await chat_about_session(session_id, body.message, body.history, db)
        resp = ChatResponse(**result)
        return resp
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    except Exception as exc:
        logger.error("chat_session_failed", session_id=session_id, error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chat request failed.",
        )


@router.post(
    "/{session_id}/generateEmbeddings",
    summary="Generate and store embeddings for a vergadering",
    description="Reads chunks_embeddings.json, calls text-embedding-3-small for each chunk, and upserts vectors into Qdrant.",
)
async def generate_session_embeddings(
    session_id: str,
    _: str = Depends(require_api_key),
) -> dict:
    try:
        result = await generate_embeddings(session_id)
        return {"status": "ok", "vergadering_id": session_id, **result}
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session data not found.")
    except Exception as exc:
        logger.error("generate_embeddings_failed", session_id=session_id, error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate embeddings.",
        )
