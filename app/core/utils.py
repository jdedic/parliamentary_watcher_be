import re
from datetime import datetime

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def validate_guid(value: str) -> str:
    """Raise ValueError if value is not a well-formed UUID, preventing path traversal."""
    if not _UUID_RE.match(value):
        raise ValueError(f"Invalid GUID: {value!r}")
    return value


def sanitize_text(text: str) -> str:
    """Strip null bytes and control characters, normalize whitespace."""
    text = text.replace("\x00", "")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()


def to_iso(value: str | None) -> datetime | None:
    """
    Parse an ISO 8601 datetime string into a Python datetime object.

    Args:
        value: ISO 8601 string or None.

    Returns:
        Parsed datetime or None if value is absent/invalid.
    """
    if not value:
        return None
    try:
        # Handle both with and without timezone suffix
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def to_int(value: str | int | None) -> int | None:
    """
    Safely convert a value to int.

    Args:
        value: Any value that can be cast to int.

    Returns:
        Integer or None if conversion fails.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
