# Architecture

## Overview

Parliamentary Summary follows a **layered architecture** where each layer has a single responsibility and dependencies flow strictly downward.

```
HTTP Request
     │
     ▼
┌─────────────────┐
│   API Routes    │  app/api/routes/      — FastAPI handlers, auth, HTTP in/out
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    Services     │  app/services/        — Business logic, orchestration
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Repositories   │  app/repositories/   — Database queries (SQLAlchemy)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│     Models      │  app/models/         — SQLAlchemy ORM table definitions
└─────────────────┘
```

## Layers

### API Routes (`app/api/routes/`)
- Receives HTTP requests
- Validates authentication via `Depends(require_api_key)`
- Calls service methods
- Returns Pydantic schemas as JSON responses
- Does **not** contain business logic or direct DB access

### Services (`app/services/`)
- Orchestrates the full sync pipeline (fetch → persist → download)
- Calls the external Tweede Kamer API via `http_client.py`
- Handles all external API error cases (network errors, HTTP errors)
- Calls repositories for DB persistence
- Does **not** know about HTTP request/response formats

### Repositories (`app/repositories/`)
- All SQLAlchemy queries live here
- Provides clean async methods: `get_all`, `get_by_id`, `exists`, `upsert`, `add_document`
- Does **not** contain business rules

### Models (`app/models/`)
- SQLAlchemy ORM class definitions
- Mirrors the database schema exactly
- Does **not** contain business logic

### Schemas (`app/schemas/`)
- Pydantic models used for API input/output validation
- Separate from ORM models intentionally (decouples DB shape from API shape)

## Core Modules (`app/core/`)

| Module | Responsibility |
|---|---|
| `config.py` | Loads settings from `.env` via `pydantic-settings` |
| `auth.py` | API key validation via FastAPI `Security` dependency |
| `database.py` | Async SQLAlchemy engine, session factory, `get_db` dependency |
| `http_client.py` | All outbound HTTP calls to Tweede Kamer API |
| `logging.py` | `structlog` configuration |
| `utils.py` | `to_iso()`, `to_int()` parsing helpers |

## Startup Sync Flow

```
App starts
    │
    ▼
lifespan() handler called
    │
    ▼
sync_sessions(db) called
    │
    ├─► fetch_vergadering_list()        — GET /Vergadering from Tweede Kamer API
    │       │
    │       ├── RequestError?           — log ERROR, raise RuntimeError (app still starts)
    │       └── HTTPStatusError?        — log ERROR, raise RuntimeError (app still starts)
    │
    ├─► for each session:
    │       ├─► repo.upsert(session)    — skip if already in DB
    │       ├─► fetch_verslag_list_raw(session_id)
    │       └─► for each verslag:
    │               ├─► repo.document_exists()  — skip if already downloaded
    │               ├─► download_verslag_xml()  — GET /Verslag({id})/resource
    │               ├─► _save_xml()             — write to storage/xml_files/{session_id}/
    │               └─► repo.add_document()     — record in DB
    │
    └─► db.commit()
```

## File Storage

XML files are stored at:
```
storage/xml_files/
└── {session_id}/
    ├── {document_id_1}.xml
    └── {document_id_2}.xml
```

The path is configurable via `XML_STORAGE_PATH` in `.env`.

## Database Schema

```
plenary_sessions
├── id (PK, string/GUID)
├── soort, titel, zaal, vergaderjaar
├── vergadering_nummer (int)
├── datum, aanvangstijd, sluiting (timestamptz)
├── kamer, gewijzigd_op, api_gewijzigd_op (timestamptz)
├── verwijderd (bool)
└── created_at (timestamptz, server default NOW())

plenary_session_documents
├── id (PK, autoincrement)
├── session_id (FK → plenary_sessions.id, CASCADE DELETE)
├── document_id (string/GUID, unique)
├── file_path (string)
└── downloaded_at (timestamptz, server default NOW())
```

## Error Handling Strategy

| Scenario | Behavior |
|---|---|
| External API network error on startup | Log ERROR, app starts without data |
| External API HTTP error on startup | Log ERROR, app starts without data |
| Single session fails to persist | Log ERROR, continue with next session |
| Single XML download fails | Log ERROR, continue with next document |
| DB error during request | 500 returned to client |
| Missing/invalid API key | 401 returned to client |
