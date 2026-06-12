from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChatEvalRecord(Base):
    __tablename__ = "chat_eval_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    run_id: Mapped[str] = mapped_column(String(100), index=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    retrieval_confidence: Mapped[str] = mapped_column(String(50))
    generation_confidence: Mapped[str | None] = mapped_column(String(50), nullable=True)
    judge_verdict: Mapped[str] = mapped_column(String(20), index=True)
    judge_grounded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    judge_answers_question: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    judge_missing_context: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    judge_missing_parts: Mapped[list] = mapped_column(JSONB, server_default="[]")
    judge_unsupported_claims: Mapped[list] = mapped_column(JSONB, server_default="[]")
    judge_entity_errors: Mapped[list] = mapped_column(JSONB, server_default="[]")
    judge_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_chunk_ids: Mapped[list] = mapped_column(JSONB, server_default="[]")
    retrieved_chunk_ids: Mapped[list] = mapped_column(JSONB, server_default="[]")
    matched_speakers: Mapped[list] = mapped_column(JSONB, server_default="[]")
    regenerated: Mapped[bool] = mapped_column(Boolean, server_default="false")
    model: Mapped[str] = mapped_column(String(50))
    latency_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_estimate_usd: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
