"""
check_final_xml_dates.py

Fetches the last 40 vergaderings and for each one checks when the final
(most recent) XML verslag was published (ApiGewijzigdOp).

Usage:
    python -m scripts.check_final_xml_dates
"""

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.http_client import http_get_json  # noqa: E402


async def fetch_last_40_vergaderings() -> list[dict]:
    """Fetch the 40 most recently modified vergaderings from the API."""
    base = str(settings.tweede_kamer_base_url).rstrip("/")
    url = f"{base}/Vergadering"
    params = {
        "$filter": "Verwijderd eq false",
        "$orderby": "ApiGewijzigdOp desc",
        "$top": "40",
    }
    raw = await http_get_json(url, params=params)
    return raw.get("value", [])


async def fetch_verslagen_for(vergadering_id: str) -> list[dict]:
    """Fetch all verslagen for a given vergadering, ordered newest first."""
    base = str(settings.tweede_kamer_base_url).rstrip("/")
    url = f"{base}/Verslag"
    params = {
        "$filter": (
            f"Verwijderd eq false and Vergadering_Id eq {vergadering_id}"
        ),
        "$orderby": "ApiGewijzigdOp desc",
    }
    raw = await http_get_json(url, params=params)
    return raw.get("value", [])


async def main() -> None:
    """Fetch vergaderings, collect XML publication dates, write JSON report."""
    print("Fetching last 40 vergaderings...")
    vergaderings = await fetch_last_40_vergaderings()
    print(f"Found {len(vergaderings)} vergaderings\n")

    results = []

    for v in vergaderings:
        vergadering_id = v.get("Id", "")

        try:
            verslagen = await fetch_verslagen_for(vergadering_id)
        except (httpx.RequestError, httpx.HTTPStatusError):
            verslagen = []

        eindpublicatie = next(
            (vl for vl in verslagen if vl.get("Soort") == "Eindpublicatie"), None
        )
        latest_tussen = verslagen[0] if verslagen else None

        if eindpublicatie:
            xml_status = "final"
        elif latest_tussen:
            xml_status = "interim_only"
        else:
            xml_status = "no_xml"

        results.append({
            "vergadering_id": vergadering_id,
            "date": (v.get("Datum") or "")[:10],
            "meeting_number": v.get("VergaderingNummer"),
            "title": v.get("Titel"),
            "parliamentary_year": v.get("Vergaderjaar"),
            "start_time": v.get("Aanvangstijd"),
            "end_time": v.get("Sluiting"),
            "xml_count": len(verslagen),
            "xml_status": xml_status,
            "eindpublicatie": {
                "verslag_id": eindpublicatie.get("Id"),
                "published_at": (
                    eindpublicatie.get("ApiGewijzigdOp")
                    or eindpublicatie.get("GewijzigdOp")
                ),
            } if eindpublicatie else None,
            "latest_tussenpublicatie": {
                "verslag_id": latest_tussen.get("Id"),
                "published_at": (
                    latest_tussen.get("ApiGewijzigdOp")
                    or latest_tussen.get("GewijzigdOp")
                ),
            } if latest_tussen and not eindpublicatie else None,
        })

    output_path = Path(__file__).resolve().parent / "vergadering_xml_dates.json"
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"Saved {len(results)} entries to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
