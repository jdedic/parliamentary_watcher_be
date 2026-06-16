import json
import uuid
from pathlib import Path

import spacy
from fastembed import SparseTextEmbedding
from openai import AsyncOpenAI, RateLimitError, APIError
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, SparseVectorParams, SparseIndexParams,
    PointStruct, SparseVector, PayloadSchemaType,
)

from app.core.config import settings
from app.core.logging import get_logger
from app.core.utils import validate_guid

logger = get_logger(__name__)

EMBEDDING_BATCH_SIZE = 100
SPARSE_MODEL_NAME = "Qdrant/bm25"

_sparse_model: SparseTextEmbedding | None = None
_nlp = None


def _get_sparse_model() -> SparseTextEmbedding:
    global _sparse_model
    if _sparse_model is None:
        _sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)
    return _sparse_model


def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("nl_core_news_sm")
    return _nlp


def _extract_entities(text: str) -> dict:
    nlp = _get_nlp()
    doc = nlp(text)
    people, orgs, locations = set(), set(), set()
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            people.add(ent.text.strip())
        elif ent.label_ == "ORG":
            orgs.add(ent.text.strip())
        elif ent.label_ in ("GPE", "LOC"):
            locations.add(ent.text.strip())
    return {
        "people": sorted(people),
        "organizations": sorted(orgs),
        "locations": sorted(locations),
    }


def _get_qdrant_client() -> AsyncQdrantClient:
    return AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
    )


async def _ensure_collection(client: AsyncQdrantClient) -> None:
    """Create the Qdrant collection with named dense + sparse vectors if it does not exist."""
    exists = await client.collection_exists(settings.qdrant_collection)
    if not exists:
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config={"dense": VectorParams(size=3072, distance=Distance.COSINE)},
            sparse_vectors_config={"sparse": SparseVectorParams(index=SparseIndexParams())},
        )
        logger.info("qdrant_collection_created", collection=settings.qdrant_collection)

    for field in ("speakers", "people", "organizations", "locations"):
        await client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name=field,
            field_schema=PayloadSchemaType.TEXT,
        )
    await client.create_payload_index(
        collection_name=settings.qdrant_collection,
        field_name="vergadering_id",
        field_schema=PayloadSchemaType.KEYWORD,
    )
    await client.create_payload_index(
        collection_name=settings.qdrant_collection,
        field_name="chunk_index",
        field_schema=PayloadSchemaType.INTEGER,
    )


async def generate_embeddings(vergadering_id: str) -> dict:
    """
    Read chunks_embeddings.json, generate dense (text-embedding-3-large) and
    sparse (BM25) vectors, and upsert both into Qdrant as named vectors.
    """
    validate_guid(vergadering_id)
    chunks_path = Path(settings.xml_storage_path) / vergadering_id / "chunks_embeddings.json"

    if not chunks_path.exists():
        raise FileNotFoundError(
            f"chunks_embeddings.json not found for {vergadering_id}. "
            "Run build_embedding_chunks first."
        )

    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    logger.info("embedding_started", vergadering_id=vergadering_id, total_chunks=len(chunks))

    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    qdrant_client = _get_qdrant_client()
    sparse_model = _get_sparse_model()

    await _ensure_collection(qdrant_client)

    embedded = 0
    failed = 0
    total_tokens = 0

    for batch_start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[batch_start: batch_start + EMBEDDING_BATCH_SIZE]
        texts = [chunk["text"] for chunk in batch]

        # Dense embeddings via OpenAI
        try:
            response = await openai_client.embeddings.create(
                model=settings.openai_embedding_model,
                input=texts,
            )
        except RateLimitError:
            logger.warning("embedding_rate_limit", vergadering_id=vergadering_id, batch_start=batch_start)
            failed += len(batch)
            continue
        except APIError as e:
            logger.error("embedding_api_error", vergadering_id=vergadering_id, batch_start=batch_start, error=str(e))
            failed += len(batch)
            continue

        # Sparse embeddings via BM25 (local, no API call)
        sparse_results = list(sparse_model.embed(texts))

        points = []
        for chunk, embedding_obj, sparse in zip(batch, response.data, sparse_results):
            vergadering = chunk.get("vergadering", {})
            speakers = list({
                u["speaker"]
                for u in chunk.get("utterances", [])
                if u.get("speaker")
            })
            entities = _extract_entities(chunk["text"])

            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector={
                        "dense": embedding_obj.embedding,
                        "sparse": SparseVector(
                            indices=sparse.indices.tolist(),
                            values=sparse.values.tolist(),
                        ),
                    },
                    payload={
                        "chunk_id": chunk["chunk_id"],
                        "vergadering_id": vergadering.get("id"),
                        "title": vergadering.get("title"),
                        "start_date": vergadering.get("start_date"),
                        "speakers": speakers,
                        "people": entities["people"],
                        "organizations": entities["organizations"],
                        "locations": entities["locations"],
                        "chunk_index": chunk.get("chunk_index", 0),
                        "text": chunk["text"],
                        "word_count": chunk.get("word_count"),
                    },
                )
            )

        await qdrant_client.upsert(
            collection_name=settings.qdrant_collection,
            points=points,
        )

        batch_tokens = response.usage.prompt_tokens
        total_tokens += batch_tokens
        embedded += len(batch)
        logger.info(
            "embedding_batch_upserted",
            vergadering_id=vergadering_id,
            batch_start=batch_start,
            batch_size=len(batch),
            batch_tokens=batch_tokens,
            total_tokens_so_far=total_tokens,
        )

    await qdrant_client.close()

    logger.info(
        "embedding_complete",
        vergadering_id=vergadering_id,
        embedded=embedded,
        failed=failed,
        total_tokens=total_tokens,
    )

    return {"embedded": embedded, "failed": failed, "total": len(chunks), "total_tokens": total_tokens}
