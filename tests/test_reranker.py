import pytest
from unittest.mock import MagicMock, patch


async def test_rerank_sorts_by_score_and_preserves_neighbors():
    from app.services.chat_service import _rerank_chunks

    chunks = [
        {"text": "chunk A", "chunk_id": "A", "is_neighbor": False},
        {"text": "chunk B", "chunk_id": "B", "is_neighbor": False},
        {"text": "chunk C", "chunk_id": "C", "is_neighbor": True},
    ]
    mock_reranker = MagicMock()
    mock_reranker.predict.return_value = [2.0, 8.5]  # B scores higher than A

    with patch("app.services.chat_service._get_reranker", return_value=mock_reranker):
        result = await _rerank_chunks("test query", chunks)

    assert result[0]["chunk_id"] == "B"
    assert result[1]["chunk_id"] == "A"
    assert result[2]["chunk_id"] == "C"
    assert result[2]["is_neighbor"] is True
    assert "rerank_score" not in result[2]


async def test_rerank_all_neighbors_returns_unchanged():
    from app.services.chat_service import _rerank_chunks

    chunks = [
        {"text": "x", "chunk_id": "X", "is_neighbor": True},
        {"text": "y", "chunk_id": "Y", "is_neighbor": True},
    ]
    result = await _rerank_chunks("query", chunks)
    assert [c["chunk_id"] for c in result] == ["X", "Y"]


async def test_rerank_empty_returns_empty():
    from app.services.chat_service import _rerank_chunks

    result = await _rerank_chunks("query", [])
    assert result == []


@pytest.mark.integration
async def test_reranker_surfaces_topically_relevant_chunk():
    from app.services.chat_service import _rerank_chunks

    housing_chunk = {
        "text": "Minister Jetten zei dat er 100.000 nieuwe woningen gebouwd moeten worden om de woningnood op te lossen.",
        "chunk_id": "housing",
        "is_neighbor": False,
    }
    healthcare_chunk = {
        "text": "De minister van Volksgezondheid sprak over de wachttijden in de zorg en het tekort aan verpleegkundigen.",
        "chunk_id": "healthcare",
        "is_neighbor": False,
    }
    neighbor_chunk = {"text": "Volgende spreker.", "chunk_id": "neighbor", "is_neighbor": True}

    # healthcare listed first — simulates cosine similarity ranking it higher than housing
    chunks = [healthcare_chunk, housing_chunk, neighbor_chunk]
    result = await _rerank_chunks("wat zei minister Jetten over huisvesting", chunks)

    assert result[0]["chunk_id"] == "housing", (
        f"reranker should surface housing chunk first, got {result[0]['chunk_id']} "
        f"(scores: housing={result[1].get('rerank_score'):.2f}, "
        f"healthcare={result[0].get('rerank_score'):.2f})"
    )
    assert result[-1]["chunk_id"] == "neighbor"
    assert result[0]["rerank_score"] > result[1]["rerank_score"]
