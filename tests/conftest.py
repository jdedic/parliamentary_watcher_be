"""
Shared test fixtures and pre-import stubs for the test suite.

Some modules (defusedxml, fastembed, qdrant-client) are not fully installed in
the lightweight test venv.  We stub them out here so tests that import app.main
or other high-level modules can still run without the full production venv.
"""

import sys
from unittest.mock import MagicMock
import pytest


def _make_defusedxml_stub():
    """Return a stub for defusedxml that exposes the xml.etree.ElementTree API."""
    import xml.etree.ElementTree as _real_ET

    stub = MagicMock()
    et_stub = MagicMock()
    # Expose the real Element / parse / fromstring so type-annotated code works
    et_stub.Element = _real_ET.Element
    et_stub.parse = _real_ET.parse
    et_stub.fromstring = _real_ET.fromstring
    et_stub.tostring = _real_ET.tostring
    stub.ElementTree = et_stub
    return stub, et_stub


_defusedxml_stub, _et_stub = _make_defusedxml_stub()

STUB_MODULES = {
    "defusedxml": _defusedxml_stub,
    "defusedxml.ElementTree": _et_stub,
    "fastembed": MagicMock(),
    "qdrant_client": MagicMock(),
    "qdrant_client.models": MagicMock(),
    "qdrant_client.async_qdrant_client": MagicMock(),
}

for _name, _stub in STUB_MODULES.items():
    if _name not in sys.modules:
        sys.modules[_name] = _stub
