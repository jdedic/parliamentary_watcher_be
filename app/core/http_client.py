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


def pick_current_verslag(verslagen: list[dict]) -> dict | None:
    """
    Pick the best available verslag for a vergadering: Eindpublicatie (final) if one
    exists, else the most recently modified Tussenpublicatie (provisional), else None
    (a lone Voorpublicatie/Casco isn't real content yet).

    Returns the verslag dict with an added ``is_final`` key, or None.
    """
    eindpublicaties = [v for v in verslagen if v.get("Soort") == "Eindpublicatie"]
    if eindpublicaties:
        return {**eindpublicaties[0], "is_final": True}

    tussenpublicaties = sorted(
        (v for v in verslagen if v.get("Soort") == "Tussenpublicatie"),
        key=lambda v: v.get("ApiGewijzigdOp") or "",
        reverse=True,
    )
    if tussenpublicaties:
        return {**tussenpublicaties[0], "is_final": False}

    return None


async def fetch_vergaderingen_with_latest_verslag(limit: int, batch_size: int) -> list[dict]:
    """
    Fetch vergaderings that have at least a Tussenpublicatie (provisional) or
    Eindpublicatie (final) verslag, newest first.

    Pages through the API in batches of ``batch_size`` until ``limit``
    qualifying vergaderings are collected or the API has no more results.

    Args:
        limit: Number of vergaderings to collect.
        batch_size: Number of vergaderings to request per API page.

    Returns:
        List of vergadering dicts, each with a ``current_verslag`` key (the verslag
        dict picked by ``pick_current_verslag``, including its ``is_final`` flag).
    """
    base = str(settings.tweede_kamer_base_url).rstrip("/")
    vergadering_url = f"{base}/Vergadering"

    collected: list[dict] = []
    skip = 0

    while len(collected) < limit:
        params = {
            "$filter": "Verwijderd eq false and Soort eq 'Plenair'",
            "$orderby": "Datum desc",
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

            verslag_raw = await fetch_verslag_list_raw(vergadering_id)
            current_verslag = pick_current_verslag(verslag_raw.get("value", []))

            if current_verslag:
                vergadering["current_verslag"] = current_verslag
                collected.append(vergadering)
                logger.debug(
                    "Vergadering with usable verslag found",
                    vergadering_id=vergadering_id,
                    is_final=current_verslag["is_final"],
                    collected=len(collected),
                )

            if len(collected) >= limit:
                break

        skip += batch_size

    logger.info(
        "Collected vergaderingen with latest verslag",
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


def _odata_escape(value: str) -> str:
    """Escape a string literal for use inside an OData $filter clause."""
    return value.replace("'", "''")


async def fetch_fractie_by_afkorting(afkorting: str) -> dict | None:
    """Look up a party by its abbreviation (e.g. 'VVD'). Reliable — low ambiguity."""
    base = str(settings.tweede_kamer_base_url).rstrip("/")
    url = f"{base}/Fractie"
    params = {
        "$filter": f"Afkorting eq '{_odata_escape(afkorting)}' and Verwijderd eq false",
        "$orderby": "DatumActief desc",
        "$top": "1",
    }
    raw = await http_get_json(url, params=params)
    results = raw.get("value", [])
    return results[0] if results else None


async def fetch_persoon_candidates(achternaam: str) -> list[dict]:
    """Find Persoon records by surname. Ambiguous — surnames are not unique, caller must disambiguate."""
    base = str(settings.tweede_kamer_base_url).rstrip("/")
    url = f"{base}/Persoon"
    params = {
        "$filter": f"Achternaam eq '{_odata_escape(achternaam)}' and Verwijderd eq false",
    }
    raw = await http_get_json(url, params=params)
    return raw.get("value", [])


async def fetch_fractiezetel_persoon(persoon_id: str) -> list[dict]:
    """Fetch a person's party-seat membership history (Van/TotEnMet date ranges)."""
    base = str(settings.tweede_kamer_base_url).rstrip("/")
    url = f"{base}/FractieZetelPersoon"
    params = {
        "$filter": f"Persoon_Id eq {persoon_id} and Verwijderd eq false",
        "$orderby": "Van desc",
    }
    raw = await http_get_json(url, params=params)
    return raw.get("value", [])


async def fetch_fractie_for_fractiezetel(fractiezetel_id: str) -> dict | None:
    """Resolve a FractieZetel_Id to its Fractie (party) record."""
    base = str(settings.tweede_kamer_base_url).rstrip("/")
    zetel = await http_get_json(f"{base}/FractieZetel({fractiezetel_id})")
    fractie_id = zetel.get("Fractie_Id")
    if not fractie_id:
        return None
    return await http_get_json(f"{base}/Fractie({fractie_id})")


async def download_persoon_photo(persoon_id: str) -> bytes:
    """Download a person's portrait photo."""
    base = str(settings.tweede_kamer_base_url).rstrip("/")
    url = f"{base}/Persoon({persoon_id})/resource"
    return await http_get_bytes(url)
