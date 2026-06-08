import json
import defusedxml.ElementTree as ET
from xml.etree.ElementTree import Element
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.core.utils import sanitize_text, validate_guid

logger = get_logger(__name__)

NS = "http://www.tweedekamer.nl/ggm/vergaderverslag/v1.0"
T = f"{{{NS}}}"


# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------


def _extract_quote(tekst_el: Element) -> str:
    """
    Return verbatim speech text from a <tekst> element.

    The first <alineaitem> of the first <alinea> is always the speaker label
    (e.g. "De heer Ellian (VVD):") so it is skipped.
    """
    paragraphs = []
    for i, alinea in enumerate(tekst_el.findall(f"{T}alinea")):
        items = alinea.findall(f"{T}alineaitem")
        start = 1 if i == 0 else 0
        for item in items[start:]:
            text = sanitize_text("".join(item.itertext()))
            if text:
                paragraphs.append(text)
    return "\n\n".join(paragraphs)


def _parse_speaker(el: Element) -> dict:
    """Extract speaker metadata from a <woordvoerder> or <interrumpant> element."""
    spreker = el.find(f"{T}spreker")
    if spreker is None:
        return {}
    voornaam = spreker.findtext(f"{T}voornaam", "").strip()
    achternaam = spreker.findtext(f"{T}achternaam", "").strip()
    return {
        "name": f"{voornaam} {achternaam}".strip(),
        "party": spreker.findtext(f"{T}fractie", "").strip() or None,
        "function": spreker.findtext(f"{T}functie", "").strip() or None,
    }


def _utterance_from(el: Element, is_interruption: bool = False, activity: str | None = None) -> dict | None:
    """Build a single utterance dict from a <woordvoerder> or <interrumpant> element."""
    speaker = _parse_speaker(el)
    if not speaker.get("name"):
        return None

    tekst_el = el.find(f"{T}tekst")
    if tekst_el is None:
        return None

    quote = _extract_quote(tekst_el)
    if not quote:
        return None

    return {
        "utterance_id": el.get("objectid"),
        "speaker": speaker["name"],
        "party": speaker["party"],
        "function": speaker["function"],
        "is_chair": el.findtext(f"{T}isvoorzitter") == "true",
        "is_interruption": is_interruption,
        "activity": activity,
        "quote": quote,
        "timestamp_start": el.findtext(f"{T}markeertijdbegin"),
        "timestamp_end": el.findtext(f"{T}markeertijdeind"),
    }


# ---------------------------------------------------------------------------
# Version selection — pick the single authoritative file
# ---------------------------------------------------------------------------


def _select_source_file(xml_files: list[Path]) -> tuple[Path, str]:
    """
    Choose the single XML file to parse for a vergadering.

    Multiple XML files for one vergadering are cumulative versions of the same
    transcript, published incrementally during the session:

    - ``Tussenpublicatie`` — interim snapshot; each newer one supersedes all
      earlier ones (same content plus additions).
    - ``Eindpublicatie``   — final corrected version; always preferred.

    Selecting the best single file avoids merging duplicated content across
    version files.

    Priority:
        1. ``Eindpublicatie`` with ``status=Gecorrigeerd`` (latest Timestamp
           if there are multiple).
        2. ``Eindpublicatie`` with any status (latest Timestamp).
        3. Latest ``Tussenpublicatie`` by Timestamp.
        4. Fallback: last file alphabetically.

    Returns:
        (selected_path, soort) tuple.
    """

    def _ts(path: Path) -> datetime:
        try:
            root = ET.parse(path).getroot()
            raw = root.get("Timestamp", "")
            return datetime.fromisoformat(raw)
        except (ValueError, ET.ParseError):
            return datetime.min

    def _meta(path: Path) -> tuple[str, str]:
        try:
            root = ET.parse(path).getroot()
            return root.get("soort", ""), root.get("status", "")
        except ET.ParseError:
            return "", ""

    gecorrigeerd = [p for p in xml_files if _meta(p) == ("Eindpublicatie", "Gecorrigeerd")]
    if gecorrigeerd:
        chosen = max(gecorrigeerd, key=_ts)
        return chosen, "Eindpublicatie/Gecorrigeerd"

    eindpublicatie = [p for p in xml_files if _meta(p)[0] == "Eindpublicatie"]
    if eindpublicatie:
        chosen = max(eindpublicatie, key=_ts)
        return chosen, "Eindpublicatie"

    tussenpublicaties = [p for p in xml_files if _meta(p)[0] == "Tussenpublicatie"]
    if tussenpublicaties:
        chosen = max(tussenpublicaties, key=_ts)
        return chosen, "Tussenpublicatie (latest)"

    return xml_files[-1], "unknown"


# ---------------------------------------------------------------------------
# Per-file extraction
# ---------------------------------------------------------------------------


def _extract_from_xml(xml_path: Path) -> tuple[dict, list[dict]]:
    """
    Parse a single XML file.

    Returns:
        (metadata, utterances) where metadata contains vergadering-level fields
        and utterances is the ordered list of speaker turns.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    vergadering = root.find(f"{T}vergadering")
    metadata = {}
    if vergadering is not None:
        metadata = {
            "title": vergadering.findtext(f"{T}titel", ""),
            "date": vergadering.findtext(f"{T}datum", ""),
            "parliamentary_year": vergadering.findtext(f"{T}vergaderjaar", ""),
            "meeting_number": vergadering.findtext(f"{T}vergaderingnummer", ""),
            "room": vergadering.findtext(f"{T}zaal", ""),
        }

    utterances: list[dict] = []
    for activiteit in root.iter(f"{T}activiteit"):
        activity = activiteit.findtext(f"{T}titel") or activiteit.findtext(f"{T}onderwerp")
        for woordvoerder in activiteit.iter(f"{T}woordvoerder"):
            u = _utterance_from(woordvoerder, is_interruption=False, activity=activity)
            if u:
                utterances.append(u)

            for interrumpant in woordvoerder.findall(f"{T}interrumpant"):
                u = _utterance_from(interrumpant, is_interruption=True, activity=activity)
                if u:
                    utterances.append(u)

    return metadata, utterances


# ---------------------------------------------------------------------------
# Chair detection
# ---------------------------------------------------------------------------


def _find_chair(utterances: list[dict]) -> dict | None:
    """
    Return the first speaker flagged as chair across all utterances.
    Ministers and other non-chair roles are excluded by the isvoorzitter flag.
    """
    for u in utterances:
        if u["is_chair"]:
            return {"name": u["speaker"], "party": u["party"]}
    return None


# ---------------------------------------------------------------------------
# Public service function
# ---------------------------------------------------------------------------


def build_transcript(vergadering_id: str) -> tuple[Path, str | None]:
    """
    Parse the authoritative XML file for a vergadering and write a transcript JSON.

    Multiple XML files per vergadering are cumulative version snapshots.
    Only the single best file is used (Eindpublicatie preferred, otherwise
    latest Tussenpublicatie) to avoid duplicated utterances.

    The JSON is saved as ``transcript.json`` inside the vergadering's storage
    directory. If it already exists it is overwritten.

    Args:
        vergadering_id: The UUID that identifies the vergadering (also the
                        subdirectory name under ``xml_storage_path``).

    Returns:
        Tuple of (path to transcript.json, chair name or None).

    Raises:
        FileNotFoundError: If the vergadering directory does not exist.
        ValueError: If no XML files are found in the directory.
    """
    validate_guid(vergadering_id)
    vergadering_dir = Path(settings.xml_storage_path) / vergadering_id

    if not vergadering_dir.exists():
        raise FileNotFoundError(f"Vergadering directory not found: {vergadering_dir}")

    xml_files = sorted(vergadering_dir.glob("*.xml"))
    if not xml_files:
        raise ValueError(f"No XML files found in {vergadering_dir}")

    source_file, source_kind = _select_source_file(xml_files)

    logger.info(
        "Building transcript",
        vergadering_id=vergadering_id,
        xml_files_available=len(xml_files),
        source_file=source_file.name,
        source_kind=source_kind,
    )

    try:
        metadata, utterances = _extract_from_xml(source_file)
    except ET.ParseError as exc:
        raise ValueError(f"Failed to parse {source_file.name}: {exc}") from exc

    chair = _find_chair(utterances)

    transcript = {
        "vergadering_id": vergadering_id,
        **metadata,
        "chair": chair,
        "source_file": source_file.name,
        "source_kind": source_kind,
        "utterances": utterances,
    }

    output_path = vergadering_dir / "transcript.json"
    output_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2))

    logger.info(
        "Transcript written",
        vergadering_id=vergadering_id,
        utterances=len(utterances),
        path=str(output_path),
    )
    chair_name = chair["name"] if chair else None
    return output_path, chair_name
