from datetime import datetime

from pydantic import BaseModel


class CreatePromptVersionRequest(BaseModel):
    content: str


class PromptVersionItem(BaseModel):
    id: int
    name: str
    version: int
    content: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PromptVersionSummary(BaseModel):
    name: str
    active_version: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PromptListResponse(BaseModel):
    prompts: list[PromptVersionSummary]
    total: int


class PromptVersionListResponse(BaseModel):
    name: str
    versions: list[PromptVersionItem]
    total: int
