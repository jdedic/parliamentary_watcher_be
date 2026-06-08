---
name: project-rag-architecture
description: Full RAG pipeline — XML → transcript → chunks → embeddings → Qdrant → hybrid retrieval → LLM-as-judge generation
metadata:
  type: project
---

Pipeline stages (all triggered in sync during startup or via API endpoints):

1. **Fetch** — `session_service.sync_sessions()` pulls vergaderings from Tweede Kamer OData API
2. **Download** — XML files saved to `storage/xml_files/{session_id}/{doc_id}.xml`
3. **Parse** — `transcript_service.build_transcript()` uses `xml.etree.ElementTree` → `transcript.json`
4. **Chunk (summarisation)** — `chunking_service.build_chunks()` → `chunks.json` (800–1200 words, exchange-aware)
5. **Chunk (embeddings)** — `embedding_chunks_service.build_embedding_chunks()` → `chunks_embeddings.json` (300–500 words, sentence-aware, NLTK Dutch)
6. **Embed** — `embedding_service.generate_embeddings()` — OpenAI `text-embedding-3-large` (dense) + BM25 fastembed (sparse) → Qdrant
7. **Summarise chunks** — `summarisation_service.summarise_vergadering()` — gpt-4.1-mini per chunk
8. **General summary** — `vergadering_summary_service.generate_vergadering_summary()` — gpt-4.1-mini from combined chunk summaries
9. **Stance extraction** — `stance_extraction_service.extract_vergadering_stances()` — gpt-4.1-mini per activity + ranking pass

**Chat retrieval** uses hybrid search (dense + sparse + entity boost via should-conditions), RRF fusion, score-gap filtering, neighbor expansion. Preprocessor (gpt-4.1-mini) extracts entities and translates queries to Dutch.

**LLM-as-judge** in `judge_service.generate_with_judge()`: generates answer → judges → regenerates once on fail/needs_review if missing parts.

**Vector store**: Qdrant with named vectors (`dense`, `sparse`), collection `plenary_chunks`. Collection auto-created on first embed. Payload fields indexed: speakers, people, organizations, locations, chunk_index.

**Why:** Parliamentary transcripts are Dutch; BM25 sparse + dense hybrid handles Dutch terminology and proper nouns well.

**How to apply:** When reviewing retrieval quality or token budgets, note that two separate chunk files exist (chunks.json and chunks_embeddings.json) for different purposes. Chunks.json is used for summarisation; chunks_embeddings.json is used for vector search.
