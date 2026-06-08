import httpx
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

TIMEOUT_SECONDS = 30


async def http_get_json(url: str, params: dict | None = None) -> dict:
    """
    Perform an async GET request and return parsed JSON.

    Raises:
        httpx.HTTPStatusError: On non-2xx responses.
        httpx.RequestError: On connection/timeout failures.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        logger.debug("Sending GET request", url=url, params=params)
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            logger.error("Request timed out", url=url, timeout=TIMEOUT_SECONDS, error=str(exc))
            raise
        except httpx.RequestError as exc:
            logger.error("Network error during GET request", url=url, error=str(exc))
            raise
        except httpx.HTTPStatusError as exc:
            logger.error(
                "API returned error response",
                url=url,
                status_code=exc.response.status_code,
                error=str(exc),
            )
            raise


async def http_get_bytes(url: str) -> bytes:
    """
    Perform an async GET request and return raw bytes (for XML downloads).

    Raises:
        httpx.HTTPStatusError: On non-2xx responses.
        httpx.RequestError: On connection/timeout failures.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        logger.debug("Downloading binary resource", url=url)
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.content
        except httpx.TimeoutException as exc:
            logger.error("Download timed out", url=url, timeout=TIMEOUT_SECONDS, error=str(exc))
            raise
        except httpx.RequestError as exc:
            logger.error("Network error during binary download", url=url, error=str(exc))
            raise
        except httpx.HTTPStatusError as exc:
            logger.error(
                "API returned error response during download",
                url=url,
                status_code=exc.response.status_code,
                error=str(exc),
            )
            raise


async def fetch_vergadering_list() -> dict:
    base = str(settings.tweede_kamer_base_url).rstrip("/")
    url = f"{base}/Vergadering"
    params = {
        "$filter": "Verwijderd eq false",
        "$orderby": "ApiGewijzigdOp asc",
    }
    if settings.sync_limit > 0:
        params["$top"] = str(settings.sync_limit)
        logger.info("Fetching sessions with limit", limit=settings.sync_limit)
    return await http_get_json(url, params=params)


async def fetch_vergaderings_with_eindpublicatie(limit: int, batch_size: int) -> list[dict]:
    """
    Fetch vergaderings that have at least one Eindpublicatie XML, newest first.

    Pages through the API in batches of ``batch_size`` until ``limit``
    qualifying vergaderings are collected or the API has no more results.

    Args:
        limit: Number of vergaderings with Eindpublicatie to collect.
        batch_size: Number of vergaderings to request per API page.

    Returns:
        List of vergadering dicts, each with a ``verslagen`` key containing
        only its Eindpublicatie records.
    """
    base = str(settings.tweede_kamer_base_url).rstrip("/")
    vergadering_url = f"{base}/Vergadering"
    verslag_url = f"{base}/Verslag"

    collected: list[dict] = []
    skip = 0

    while len(collected) < limit:
        params = {
            "$filter": "Verwijderd eq false",
            "$orderby": "ApiGewijzigdOp desc",
            "$top": str(batch_size),
            "$skip": str(skip),
        }
        raw = await http_get_json(vergadering_url, params=params)
        batch: list[dict] = raw.get("value", [])

        if not batch:
            logger.info("No more vergaderings from API, stopping early")
            break

        for vergadering in batch:
            vergadering_id = vergadering.get("Id")
            if not vergadering_id:
                continue

            verslag_params = {
                "$filter": (
                    f"Verwijderd eq false"
                    f" and Vergadering_Id eq {vergadering_id}"
                    f" and Soort eq 'Eindpublicatie'"
                ),
                "$orderby": "ApiGewijzigdOp desc",
            }
            verslag_raw = await http_get_json(verslag_url, params=verslag_params)
            eindpublicaties: list[dict] = verslag_raw.get("value", [])

            if eindpublicaties:
                vergadering["verslagen"] = eindpublicaties
                collected.append(vergadering)
                logger.debug(
                    "Vergadering with Eindpublicatie found",
                    vergadering_id=vergadering_id,
                    collected=len(collected),
                )

            if len(collected) >= limit:
                break

        skip += batch_size

    logger.info(
        "Collected vergaderings with Eindpublicatie",
        requested=limit,
        found=len(collected),
    )
    return collected


async def fetch_verslag_list_raw(vergadering_id: str) -> dict:
    """
    Fetch all verslagen (transcripts) linked to a given vergadering (session).

    Args:
        vergadering_id: The GUID of the plenary session.

    Returns:
        Raw JSON response dict with OData structure.
    """
    base = str(settings.tweede_kamer_base_url).rstrip("/")
    url = f"{base}/Verslag"
    params = {
        "$filter": f"Verwijderd eq false and Vergadering_Id eq {vergadering_id}",
        "$orderby": "ApiGewijzigdOp asc",
    }
    return await http_get_json(url, params=params)


async def download_verslag_xml(verslag_id: str) -> bytes:
    """
    Download the XML resource for a given verslag.

    Args:
        verslag_id: The GUID of the verslag document.

    Returns:
        Raw XML bytes.
    """
    base = str(settings.tweede_kamer_base_url).rstrip("/")
    url = f"{base}/Verslag({verslag_id})/resource"
    return await http_get_bytes(url)
