# ParlAI — Parliamentary Session Backend

FastAPI backend for processing Dutch Tweede Kamer plenary sessions. Ingests XML transcripts, chunks and embeds them into Qdrant, generates summaries and political stances, and serves a RAG chat interface.

## Features

- Automatic sync with the Tweede Kamer OData API
- XML transcript ingestion and sentence-aware chunking
- Hybrid vector search (dense + BM25 sparse) via Qdrant
- LLM-generated summaries and per-speaker political stances (Dutch + English)
- RAG chat interface with LLM-as-a-judge evaluation
- Eval logging to PostgreSQL and JSONL
- Streamlit evaluation dashboard

## Tech Stack

- **Framework**: FastAPI + SQLAlchemy 2.0 (asyncpg)
- **Database**: PostgreSQL (Alembic migrations)
- **Vector store**: Qdrant (hybrid dense + sparse)
- **LLMs**: OpenAI `gpt-4.1` (generation), `gpt-4.1-mini` (judge, translation, summarisation)
- **Embeddings**: `text-embedding-3-large`
- **Scheduler**: APScheduler (background sync every 12 hours)

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL
- Qdrant instance
- OpenAI API key

### Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m spacy download nl_core_news_sm
```

Create a `.env` file (see `.env.example`):

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/parliamentary_summary
API_KEY=your-api-key
OPENAI_API_KEY=your-openai-key
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
```

### Run migrations

```bash
alembic upgrade head
```

### Start the server

```bash
uvicorn app.main:app --reload
```

API docs available at `http://127.0.0.1:8000/docs`.

## API Overview

All endpoints require an `X-API-Key` header.

### Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/sessions` | List sessions (filter by status, title, meeting number) |
| `GET` | `/api/v1/sessions/{id}` | Get session by ID |
| `POST` | `/api/v1/sessions/sync` | Manually trigger sync with Tweede Kamer API |
| `POST` | `/api/v1/sessions/{id}/createEmbeddingsChunks` | Build embedding chunks from transcript |
| `POST` | `/api/v1/sessions/{id}/generateEmbeddings` | Generate and upsert vectors into Qdrant |
| `POST` | `/api/v1/sessions/{id}/summarise` | Generate session summary |
| `POST` | `/api/v1/sessions/{id}/extractStances` | Extract per-speaker political stances |
| `POST` | `/api/v1/sessions/{id}/chat` | RAG chat about a session |

### Pipeline order

For a newly ingested session, run steps in this order:

```
sync → createEmbeddingsChunks → generateEmbeddings → summarise → extractStances
```

## Eval Dashboard

A Streamlit dashboard for inspecting RAG evaluation results.

```bash
streamlit run eval_dashboard.py
```

Requires `DATABASE_URL` to be set. Uses `requirements-dashboard.txt`.

## Deployment

The project includes two Dockerfiles:

- `Dockerfile` — FastAPI backend (includes spaCy, NLTK)
- `Dockerfile.dashboard` — Streamlit eval dashboard (lightweight)

Both services share the same PostgreSQL database.
