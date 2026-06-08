---
name: project-codebase-architecture
description: Module layout, key files, and architectural patterns for the Parliamentary Summary FastAPI backend
metadata:
  type: project
---

**Entry point**: `app/main.py` — lifespan handler does startup sync + starts APScheduler

**Layers** (top-down):
- `app/api/routes/sessions.py` — single router file with all endpoints
- `app/services/` — all business logic, LLM calls, file I/O
- `app/repositories/plenary_session_repository.py` — all DB queries via SQLAlchemy async
- `app/models/plenary_session.py` — ORM models
- `app/schemas/plenary_session.py` — Pydantic request/response models

**Core infrastructure** (`app/core/`):
- `config.py` — pydantic-settings, loads from `.env`
- `auth.py` — API key validation via `X-API-Key` header, `Depends(require_api_key)`
- `database.py` — async SQLAlchemy engine, `get_db` dependency
- `http_client.py` — all outbound calls to Tweede Kamer OData API (httpx async)
- `locks.py` — per-vergadering asyncio.Lock dict (prevents concurrent processing)
- `scheduler.py` — APScheduler AsyncIOScheduler for periodic sync
- `logging.py` — structlog with DailyFileHandler (relative path `logs/`)

**Key architectural patterns**:
- `SessionService` class uses `Depends()` injection with nested `get_db`
- Raw module-level functions (`sync_sessions`, `list_sessions`) coexist with class-based `SessionService` — minor inconsistency
- OpenAI and Qdrant clients are instantiated per-request (no shared connection pool)
- `_locks` dict in `locks.py` never evicts entries — grows with unique vergadering IDs

**Storage layout**:
- XML: `storage/xml_files/{session_id}/{doc_id}.xml`
- Transcript: `storage/xml_files/{session_id}/transcript.json`
- Chunks (summarisation): `storage/xml_files/{session_id}/chunks.json`
- Chunks (embeddings): `storage/xml_files/{session_id}/chunks_embeddings.json`
- Eval log: `storage/chat_eval.jsonl` (sibling of `xml_files/`)

**DB**: PostgreSQL via asyncpg. Alembic migrations. Two tables: `plenary_sessions`, `plenary_session_documents`.
