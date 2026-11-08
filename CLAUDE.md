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
- Rate limit for chat is `chat_rate_limit` in config (currently `20/minute`, keyed per client IP, in-memory per process).

## Key files
- `app/services/chat_service.py` — RAG engine. Do not modify without explicit instruction.
- `app/services/judge_service.py` — LLM-as-a-judge with JSON structured output. Verdicts: `pass`, `needs_review`, `fail`.
- `app/services/translation_service.py` — Dutch → English translation via GPT-4.1-mini.
- `app/services/prompt_registry.py` — in-memory prompt cache. `get_prompt(name, **kwargs)` for sync lookup; `load_all_prompts()` called at startup.
- `app/core/config.py` — all environment settings.

## Prompt versioning
All system prompts are stored in the `prompt_versions` PostgreSQL table — never hardcoded in service files. Services call `get_prompt("name")` from `prompt_registry.py`.

**Prompt names and their roles:**
| Name | Role |
|------|------|
| `rag_assistant` | Main parliamentary chat system prompt — has `{context}` and `{answer_language}` placeholders |
| `query_preprocessor` | Translates query to Dutch, extracts people/orgs/topic keywords for BM25 — `entity_query` must include topic terms, not just names |
| `answer_quality_judge` | RAG grounding and completeness evaluator |
| `chunk_summariser` | Single chunk → 3-5 sentence Dutch summary |
| `session_summariser` | Full session → 300-500 word neutral Dutch summary |
| `stance_extractor` | Speaker stance extraction per debate activity |
| `stance_ranker` | Selects top 10-20 politically significant stances |
| `summary_translator` | Dutch → English session summary translation |
| `stances_translator` | Dutch → English stance translation |

**To update a prompt without redeploying:**
1. `POST /api/v1/admin/prompts/{name}` with `{"content": "..."}` → creates new version
2. `PUT /api/v1/admin/prompts/{name}/activate/{version}` → hot-reloads cache immediately
3. Every chat eval record stores which version was active (`prompt_version` column in `chat_eval_records`, format: `rag_assistant@v2`)

**Never add hardcoded prompt strings to service files** — always go through the registry.

## Chat access keys (user passwords)
**Chat is currently open** — `chat_require_key` in config defaults to `False`, so `require_chat_key` returns `None` and `/auth/chat` accepts any code. Set `CHAT_REQUIRE_KEY=true` to re-enable the key gate; everything below applies only then. While open, the per-IP `chat_rate_limit` is the only guard, and eval records have no `access_key_id`.

When enabled, users access the chat via a 12-character key (`secrets.token_urlsafe(9)`, e.g. `xK9mZ3pQrL2v`) sent in the `X-Chat-Key` header.

- Keys are stored in `chat_access_keys` table (`app/models/chat_access.py`)
- Managed via `POST/GET/DELETE /api/v1/admin/keys` (requires `X-API-Key`)
- **Auto-revoke**: keys expire automatically when `requests_used >= max_requests` OR `tokens_used >= max_tokens`. Set these limits when creating a key; `null` means unlimited.
- Admin keys (`is_admin: true`) are never rate-limited or auto-revoked
- Key generation: `app/repositories/chat_access_repository.py` → `create()`

## Chat audit logging
`ChatAuditMiddleware` (`app/core/chat_audit.py`) logs one `chat_attempt` line per POST to `/sessions/{id}/chat` and `/auth/chat` — including 401/403/429/500 rejections, which never reach the route or `chat_eval_records`. Fields: endpoint, session_id, status, ip, forwarded_for, user_agent, key_present, access_key_id, latency_ms. Never log the raw key; auth code sets `request.state.chat_access_key_id` once a key resolves. Only successful chats are stored in the DB (`chat_eval_records`).

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
