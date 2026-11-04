"""The incident-response adapter: incident-handling, every declaration not covered until the companion records its declared side.
The reasons and 3c's rulings are in adapters/unread_only.py."""

from __future__ import annotations

from ..models import Register
from ..policy import Loaded
from .unread_only import lines_for

COMPANION = "handbook/incident-response"


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    return lines_for(COMPANION, records, pol, register, capability)
