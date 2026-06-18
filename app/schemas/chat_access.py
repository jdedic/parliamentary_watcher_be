from datetime import datetime

from pydantic import BaseModel, Field


class CreateKeyRequest(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    is_admin: bool = False
    max_requests: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)


class KeyResponse(BaseModel):
    id: int
    key: str
    label: str | None
    is_admin: bool
    max_requests: int | None
    requests_used: int
    max_tokens: int | None
    tokens_used: int
    created_at: datetime

    model_config = {"from_attributes": True}


class KeyListItem(BaseModel):
    id: int
    label: str | None
    is_admin: bool
    max_requests: int | None
    requests_used: int
    max_tokens: int | None
    tokens_used: int
    created_at: datetime

    model_config = {"from_attributes": True}


class KeyListResponse(BaseModel):
    keys: list[KeyListItem]
    total: int


class KeyHistoryEntry(BaseModel):
    id: int
    session_id: str
    question: str
    answer: str
    ip_address: str | None
    key_label: str | None
    judge_verdict: str
    input_tokens: int
    output_tokens: int
    cost_estimate_usd: float
    created_at: datetime

    model_config = {"from_attributes": True}


class KeyHistoryResponse(BaseModel):
    key_id: int
    label: str | None
    entries: list[KeyHistoryEntry]
    total: int
