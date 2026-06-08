import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.session_service import sync_sessions, list_sessions
from app.models.plenary_session import SessionStatus


MOCK_VERSLAG = {
    "Id": "doc-guid-001",
    "Verwijderd": False,
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
    "verslagen": [MOCK_VERSLAG],
}


@pytest.mark.asyncio
async def test_sync_sessions_success():
    """Test that sync_sessions correctly persists sessions and documents."""
    mock_db = AsyncMock(spec=AsyncSession)

    with (
        patch(
            "app.services.session_service.fetch_vergaderings_with_eindpublicatie",
            new_callable=AsyncMock,
            return_value=[MOCK_SESSION],
        ),
        patch(
            "app.services.session_service.download_verslag_xml",
            new_callable=AsyncMock,
            return_value=b"<xml>content</xml>",
        ),
        patch(
            "app.services.session_service.PlenarySessionRepository"
        ) as MockRepo,
        patch("app.services.session_service._save_xml", return_value="storage/xml_files/test-guid-001/doc-guid-001.xml"),
    ):
        mock_repo = MagicMock()
        mock_repo.upsert = AsyncMock()
        mock_repo.exists = AsyncMock(return_value=False)
        mock_repo.document_exists = AsyncMock(return_value=False)
        mock_repo.add_document = AsyncMock()
        mock_repo.get_status = AsyncMock(return_value=SessionStatus.SUMMARISED)
        MockRepo.return_value = mock_repo

        result = await sync_sessions(mock_db)

    assert result["total_fetched"] == 1
    assert mock_db.commit.call_count == 2


@pytest.mark.asyncio
async def test_sync_sessions_api_unreachable():
    """Test that a network error raises RuntimeError with a clear message."""
    mock_db = AsyncMock(spec=AsyncSession)

    with patch(
        "app.services.session_service.fetch_vergaderings_with_eindpublicatie",
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
        "app.services.session_service.fetch_vergaderings_with_eindpublicatie",
        new_callable=AsyncMock,
        side_effect=httpx.HTTPStatusError(
            "Service Unavailable", request=mock_request, response=mock_response
        ),
    ):
        with pytest.raises(RuntimeError, match="HTTP 503"):
            await sync_sessions(mock_db)
