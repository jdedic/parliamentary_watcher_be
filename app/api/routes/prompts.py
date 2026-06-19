from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key
from app.core.database import get_db
from app.core.logging import get_logger
from app.repositories.prompt_repository import PromptRepository
from app.schemas.prompt_version import (
    CreatePromptVersionRequest,
    PromptListResponse,
    PromptVersionItem,
    PromptVersionListResponse,
    PromptVersionSummary,
)
from app.services.prompt_registry import reload_prompts

router = APIRouter(prefix="/admin/prompts", tags=["Admin — Prompts"])
logger = get_logger(__name__)


@router.get("", response_model=PromptListResponse, summary="List all prompts with active version")
async def list_prompts(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> PromptListResponse:
    repo = PromptRepository(db)
    active = await repo.get_all_names()
    return PromptListResponse(
        prompts=[
            PromptVersionSummary(name=pv.name, active_version=pv.version, created_at=pv.created_at)
            for pv in active
        ],
        total=len(active),
    )


@router.post("/reload", status_code=200, summary="Force reload prompt cache from DB")
async def reload_prompt_cache(_: str = Depends(require_api_key)) -> dict:
    await reload_prompts()
    return {"status": "reloaded"}


@router.get("/{name}", response_model=PromptVersionListResponse, summary="List all versions for a prompt")
async def list_prompt_versions(
    name: str,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> PromptVersionListResponse:
    repo = PromptRepository(db)
    versions = await repo.get_versions_for_name(name)
    if not versions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Prompt '{name}' not found.")
    return PromptVersionListResponse(
        name=name,
        versions=[PromptVersionItem.model_validate(v) for v in versions],
        total=len(versions),
    )


@router.post("/{name}", response_model=PromptVersionItem, status_code=201, summary="Create a new prompt version")
async def create_prompt_version(
    name: str,
    body: CreatePromptVersionRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> PromptVersionItem:
    repo = PromptRepository(db)
    existing = await repo.get_versions_for_name(name)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prompt '{name}' not found. Only existing prompts can be versioned.",
        )
    pv = await repo.create(name=name, content=body.content)
    await db.commit()
    await db.refresh(pv)
    logger.info("prompt_version_created", name=name, version=pv.version)
    return PromptVersionItem.model_validate(pv)


@router.put("/{name}/activate/{version}", response_model=PromptVersionItem, summary="Activate a specific prompt version")
async def activate_prompt_version(
    name: str,
    version: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(require_api_key),
) -> PromptVersionItem:
    repo = PromptRepository(db)
    pv = await repo.activate(name=name, version=version)
    if pv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Prompt '{name}' version {version} not found.",
        )
    await db.commit()
    await reload_prompts()
    logger.info("prompt_version_activated", name=name, version=version)
    return PromptVersionItem.model_validate(pv)
