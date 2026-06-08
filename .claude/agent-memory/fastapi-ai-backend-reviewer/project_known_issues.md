---
name: project-known-issues
description: Production-blocking and high-severity issues found during first full audit (2026-06-06)
metadata:
  type: project
---

**Critical / Security:**
- `.env.example` contains a real OpenAI API key (`sk-proj-vOHpotSQ...`) and a real Qdrant API key — committed to repo, must be rotated
- `.env` (also present in repo checkout) contains the same live OpenAI key
- `xml.etree.ElementTree` used without DTD restrictions — no defusedxml protection; source XML comes from external API but no sanitization if storage files are tampered
- `session_id` and `doc_id` from external API used directly to construct filesystem paths in `_save_xml` without UUID validation/path canonicalization
- All 500 error details (`str(exc)`) exposed directly in HTTPException `detail` field in every route handler

**Critical / Logic:**
- `sync_sessions` status condition at line 181 is inverted: `if current_status != SessionStatus.DOWNLOADED` runs the full pipeline for sessions that are NOT yet downloaded — should be `== SessionStatus.DOWNLOADED` or checking for None/FAILED
- Tests in `test_session_service.py` patch `fetch_vergadering_list` and `fetch_verslag_list_raw`, but `sync_sessions` actually calls `fetch_vergaderings_with_eindpublicatie` — tests pass trivially and do not exercise real code path

**High / Async:**
- `build_transcript()`, `build_chunks()`, `build_embedding_chunks()` are synchronous functions called directly inside `async def sync_sessions()` and `async def create_embedding_chunks()` — blocks the event loop during CPU/IO-bound XML parsing and file writes
- `_get_sparse_model()` and `_get_nlp()` (spaCy) are module-level blocking loaders called from async context on first request

**High / Production:**
- `structlog.dev.ConsoleRenderer()` hardcoded — comment says to switch to JSONRenderer but it's never done; machine-parseable logs not available
- `LOGS_DIR = Path("logs")` is a relative path — breaks when process working directory differs from project root
- `xml_storage_path = "storage/xml_files"` is a relative path with the same issue
- No retry with exponential backoff on any OpenAI call — bare `asyncio.sleep(10)` on rate limit, no retry at all in most services
- `summarisation_service` and `vergadering_summary_service` have no `max_tokens` on OpenAI calls — unbounded output

**Medium:**
- `import imp` at top of `session_service.py` — `imp` module removed in Python 3.12; not used but will crash on import
- 10+ `print()` statements scattered through `chat_service.py` — debug output goes to stdout in production
- OpenAI and Qdrant clients instantiated per-request rather than shared
- `_locks` dict in `locks.py` never evicted — unbounded memory growth over time
- `eval_logger.py` writes to `chat_eval.jsonl` synchronously in an async handler
- `summarise_session` and related endpoints have no `max_tokens` guard on the combined chunk summaries input — can exceed context window
- `history` in chat: 20 items × 4000 chars each = up to 80,000 chars not accounted for in token budget

**How to apply:** Prioritize secrets rotation, the inverted status condition, the sync-in-async blocking calls, and the test/code mismatch before any deployment.
