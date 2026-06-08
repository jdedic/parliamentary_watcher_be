import json
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, field_validator, Field
from app.models.plenary_session import SessionStatus


class PlenarySessionDocumentSchema(BaseModel):
    """Schema for a session document."""

    id: int
    session_id: str
    document_id: str
    downloaded_at: datetime

    model_config = {"from_attributes": True}


class PlenarySessionSchema(BaseModel):
    """Schema for a plenary session returned to the client."""

    id: str
    kind: str | None
    title: str | None
    room: str | None
    parliamentary_year: str | None
    meeting_number: int | None
    date: datetime | None
    start_time: datetime | None
    end_time: datetime | None
    chamber: str | None
    modified_at: datetime | None
    api_modified_at: datetime | None
    deleted: bool
    chair: str | None
    status: SessionStatus | None
    created_at: datetime
    summary: str | None = None
    stances: Any | None = None
    summary_sources: Any | None = None
    summary_en: str | None = None
    stances_en: Any | None = None
    documents: list[PlenarySessionDocumentSchema] = []

    model_config = {"from_attributes": True}

    @field_validator("stances", mode="before")
    @classmethod
    def parse_stances(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return v
        return v

    @field_validator("summary_sources", mode="before")
    @classmethod
    def parse_summary_sources(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return v
        return v

    @field_validator("stances_en", mode="before")
    @classmethod
    def parse_stances_en(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return v
        return v


class PlenarySessionListItemSchema(BaseModel):
    """Lightweight session schema for list views."""

    id: str
    title: str | None
    date: datetime | None
    room: str | None
    chair: str | None
    summary: str | None = None
    summary_en: str | None = None
    status: SessionStatus | None
    meeting_number: int | None
    parliamentary_year: str | None

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    """Paginated list of plenary sessions."""

    total: int
    sessions: list[PlenarySessionListItemSchema]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default=[], max_length=20)


class ChatResponse(BaseModel):
    answer: str
    retrieved_chunk_ids: list[str]
    matched_speakers: list[str]
    retrieval_confidence: Literal["high", "medium", "low"]
    generation_confidence: Literal["high", "medium", "low"]
    judge_verdict: Literal["pass", "needs_review", "fail"]
