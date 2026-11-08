import pytest
import httpx
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.session_service import sync_sessions, list_sessions
from app.models.plenary_session import SessionStatus


MOCK_TUSSENPUBLICATIE = {
    "Id": "doc-guid-001",
    "Soort": "Tussenpublicatie",
    "ApiGewijzigdOp": "2026-06-03T10:00:00Z",
    "is_final": False,
}

MOCK_EINDPUBLICATIE = {
    "Id": "doc-guid-002",
    "Soort": "Eindpublicatie",
    "ApiGewijzigdOp": "2026-07-31T10:00:00Z",
    "is_final": True,
}

MOCK_SESSION = {
    "Id": "test-guid-001",
    "Soort": "Plenaire vergadering",
    "Titel": "Vergadering 1",
    "Zaal": "Plenaire zaal",
    "Vergaderjaar": "2023-2024",
    "VergaderingNummer": "10",
    "Datum": "2024-01-15T00:00:00Z",
    "Aanvangstijd": "2024-01-15T10:00:00Z",
    "Sluiting": "2024-01-15T18:00:00Z",
    "Kamer": "Tweede Kamer",
    "GewijzigdOp": "2024-01-15T19:00:00Z",
    "ApiGewijzigdOp": "2024-01-15T19:05:00Z",
    "Verwijderd": False,
    "current_verslag": MOCK_TUSSENPUBLICATIE,
}


def _make_mock_repo(**overrides) -> MagicMock:
    """A MagicMock PlenarySessionRepository with sensible async defaults."""
    repo = MagicMock()
    repo.upsert = AsyncMock()
    repo.exists = AsyncMock(return_value=False)
    repo.document_exists = AsyncMock(return_value=False)
    repo.add_document = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=None)
    repo.update_publication_state = AsyncMock()
    repo.update_chair = AsyncMock()
    repo.update_status = AsyncMock()
    repo.get_non_final_ids = AsyncMock(return_value=[])
    for name, value in overrides.items():
        setattr(repo, name, value)
    return repo


PIPELINE_PATCH_TARGETS = [
    "build_transcript",
    "build_chunks",
    "build_embedding_chunks",
    "generate_embeddings",
    "summarise_vergadering",
    "extract_vergadering_stances",
    "generate_vergadering_summary",
]


class _PipelineMocks:
    """Context manager patching every reprocessing-pipeline step as a no-op AsyncMock."""

    def __enter__(self):
        self._patchers = [
            patch(f"app.services.session_service.{name}", new_callable=AsyncMock)
            for name in PIPELINE_PATCH_TARGETS
        ]
        mocks = [p.start() for p in self._patchers]
        mocks[0].return_value = (None, None)  # build_transcript -> (transcript, chair_name)
        for name, mock in zip(PIPELINE_PATCH_TARGETS, mocks):
            setattr(self, name, mock)
        return self

    def __exit__(self, *exc):
        for p in self._patchers:
            p.stop()


@pytest.mark.asyncio
async def test_sync_sessions_new_provisional_session_ingested():
    """A brand-new session with only a Tussenpublicatie is persisted, downloaded, and fully processed."""
    mock_db = AsyncMock(spec=AsyncSession)
    mock_repo = _make_mock_repo()

    with (
        patch(
            "app.services.session_service.fetch_vergaderingen_with_latest_verslag",
            new_callable=AsyncMock,
            return_value=[MOCK_SESSION],
        ),
        patch(
            "app.services.session_service.download_verslag_xml",
            new_callable=AsyncMock,
            return_value=b"<xml>content</xml>",
        ),
        patch("app.services.session_service.PlenarySessionRepository", return_value=mock_repo),
        patch("app.services.session_service._save_xml", return_value="storage/xml_files/test-guid-001/doc-guid-001.xml"),
        _PipelineMocks() as pipeline,
    ):
        result = await sync_sessions(mock_db)

    assert result["total_fetched"] == 1
    assert result["new_sessions"] == 1
    assert result["new_documents"] == 1
    assert result["reprocessed"] == 1
    mock_repo.update_publication_state.assert_awaited_once_with(
        "test-guid-001", current_verslag_id="doc-guid-001", is_final=False
    )
    pipeline.build_transcript.assert_awaited_once_with("test-guid-001")


@pytest.mark.asyncio
async def test_sync_sessions_unchanged_session_is_noop():
    """Re-syncing a session whose current verslag hasn't changed downloads nothing and skips the pipeline."""
    mock_db = AsyncMock(spec=AsyncSession)
    existing = SimpleNamespace(current_verslag_id="doc-guid-001")
    mock_repo = _make_mock_repo(
        exists=AsyncMock(return_value=True),
        document_exists=AsyncMock(return_value=True),
        get_by_id=AsyncMock(return_value=existing),
    )

    with (
        patch(
            "app.services.session_service.fetch_vergaderingen_with_latest_verslag",
            new_callable=AsyncMock,
            return_value=[MOCK_SESSION],
        ),
        patch("app.services.session_service.PlenarySessionRepository", return_value=mock_repo),
        _PipelineMocks() as pipeline,
    ):
        result = await sync_sessions(mock_db)

    assert result["new_sessions"] == 0
    assert result["new_documents"] == 0
    assert result["reprocessed"] == 0
    pipeline.build_transcript.assert_not_awaited()
    pipeline.generate_embeddings.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_sessions_newer_tussenpublicatie_triggers_reprocess():
    """A pending session (found via get_non_final_ids, not this run's discovery) whose
    Tussenpublicatie was revised gets re-downloaded and reprocessed."""
    mock_db = AsyncMock(spec=AsyncSession)
    existing = SimpleNamespace(current_verslag_id="doc-guid-old")
    mock_repo = _make_mock_repo(
        exists=AsyncMock(return_value=True),
        get_by_id=AsyncMock(return_value=existing),
        get_non_final_ids=AsyncMock(return_value=["test-guid-001"]),
    )

    with (
        patch(
            "app.services.session_service.fetch_vergaderingen_with_latest_verslag",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.services.session_service.fetch_verslag_list_raw",
            new_callable=AsyncMock,
            return_value={"value": [MOCK_TUSSENPUBLICATIE]},
        ),
        patch(
            "app.services.session_service.download_verslag_xml",
            new_callable=AsyncMock,
            return_value=b"<xml>content</xml>",
        ),
        patch("app.services.session_service.PlenarySessionRepository", return_value=mock_repo),
        patch("app.services.session_service._save_xml", return_value="storage/xml_files/test-guid-001/doc-guid-001.xml"),
        _PipelineMocks() as pipeline,
    ):
        result = await sync_sessions(mock_db)

    assert result["reprocessed"] == 1
    mock_repo.update_publication_state.assert_awaited_once_with(
        "test-guid-001", current_verslag_id="doc-guid-001", is_final=False
    )
    pipeline.build_transcript.assert_awaited_once_with("test-guid-001")


@pytest.mark.asyncio
async def test_sync_sessions_promotion_to_eindpublicatie():
    """A pending session promoted to Eindpublicatie is reprocessed and marked final."""
    mock_db = AsyncMock(spec=AsyncSession)
    existing = SimpleNamespace(current_verslag_id="doc-guid-001")  # was on the Tussenpublicatie
    mock_repo = _make_mock_repo(
        exists=AsyncMock(return_value=True),
        get_by_id=AsyncMock(return_value=existing),
        get_non_final_ids=AsyncMock(return_value=["test-guid-001"]),
    )

    with (
        patch(
            "app.services.session_service.fetch_vergaderingen_with_latest_verslag",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.services.session_service.fetch_verslag_list_raw",
            new_callable=AsyncMock,
            return_value={"value": [MOCK_TUSSENPUBLICATIE, MOCK_EINDPUBLICATIE]},
        ),
        patch(
            "app.services.session_service.download_verslag_xml",
            new_callable=AsyncMock,
            return_value=b"<xml>content</xml>",
        ),
        patch("app.services.session_service.PlenarySessionRepository", return_value=mock_repo),
        patch("app.services.session_service._save_xml", return_value="storage/xml_files/test-guid-001/doc-guid-002.xml"),
        _PipelineMocks(),
    ):
        result = await sync_sessions(mock_db)

    assert result["reprocessed"] == 1
    mock_repo.update_publication_state.assert_awaited_once_with(
        "test-guid-001", current_verslag_id="doc-guid-002", is_final=True
    )


@pytest.mark.asyncio
async def test_sync_sessions_api_unreachable():
    """Test that a network error raises RuntimeError with a clear message."""
    mock_db = AsyncMock(spec=AsyncSession)

    with patch(
        "app.services.session_service.fetch_vergaderingen_with_latest_verslag",
        new_callable=AsyncMock,
        side_effect=httpx.RequestError("Connection refused"),
    ):
        with pytest.raises(RuntimeError, match="External API is unreachable"):
            await sync_sessions(mock_db)


@pytest.mark.asyncio
async def test_sync_sessions_api_http_error():
    """Test that an HTTP error raises RuntimeError with the status code."""
    mock_db = AsyncMock(spec=AsyncSession)

    mock_request = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 503

    with patch(
        "app.services.session_service.fetch_vergaderingen_with_latest_verslag",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError(
            "Service Unavailable", request=mock_request, response=mock_response
        ),
    ):
        with pytest.raises(RuntimeError, match="HTTP 503"):
            await sync_sessions(mock_db)
