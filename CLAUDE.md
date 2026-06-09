# ParlAI — Claude Instructions

## What this project is
FastAPI backend for processing Dutch parliamentary (Tweede Kamer) plenary sessions. Ingests XML transcripts, chunks and embeds them into Qdrant, generates summaries and political stances, and serves a RAG chat interface.

## Running the app
```bash
source venv/bin/activate
uvicorn app.main:app --reload
```
Runs on `http://127.0.0.1:8000`. Docs at `/docs`.

## Architecture rules
- Strict layered architecture: routes → services → repositories → models. Never skip layers.
- All DB access goes through `PlenarySessionRepository` (`app/repositories/plenary_session_repository.py`).
- Config is Pydantic Settings in `app/core/config.py` — use env vars to override, never hardcode values.
- Rate limit for chat is `chat_rate_limit` in config (currently `20/minute`).

## Key files
- `app/services/chat_service.py` — RAG engine. Do not modify without explicit instruction.
- `app/services/judge_service.py` — LLM-as-a-judge with JSON structured output. Verdicts: `pass`, `needs_review`, `fail`.
- `app/services/translation_service.py` — Dutch → English translation via GPT-4.1-mini.
- `app/core/config.py` — all environment settings.

## Translation rules — always enforce
- Preserve proper nouns exactly: people's names, party names (VVD, D66, PVV…), institutions, policy terms, Dutch abbreviations.
- Never translate the `speaker` or `evidence` fields in stances — only `summary` and `activity`.

## Database
PostgreSQL at `postgresql+asyncpg://jdedic@localhost:5432/parliamentary_summary`.
Migrations managed by Alembic (`alembic upgrade head` to apply).

## External APIs
- **Tweede Kamer OData**: `https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0`
  - XML download: `GET /Verslag({document_id})/resource`
  - Session GUID ≠ document GUID — always use `document_id` from `plenary_session_documents` for the resource endpoint.
- **Qdrant**: collection `plenary_chunks`, hybrid dense (3072-dim) + sparse (BM25) vectors.
- **OpenAI**: `gpt-4.1` for generation, `gpt-4.1-mini` for judge/preprocessor/translation, `text-embedding-3-large` for embeddings.

## Coding conventions
- All public service functions that do file I/O must be `async def` + use `aiofiles`.
- No `asyncio.get_event_loop().run_in_executor()` — use `asyncio.to_thread()` for CPU-bound sync code.
- No comments explaining what code does — only why, when non-obvious.
- Structured logging via `structlog` (`get_logger(__name__)`).

## Things to always check before modifying
- Adding DB columns requires a new Alembic migration file.
- Schema changes (`app/schemas/plenary_session.py`) must be reflected in both `PlenarySessionSchema` and `PlenarySessionListItemSchema`.
- Pipeline endpoint order: ingest → createEmbeddingsChunks → generateEmbeddings → summarise → extractStances.
