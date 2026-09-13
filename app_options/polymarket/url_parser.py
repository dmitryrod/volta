"""Parse Polymarket event slug from user-facing URLs."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_EVENT_PATH = re.compile(r"/event/([^/?#]+)")


def parse_event_slug_from_url(url: str) -> str:
    """Extract event slug from Polymarket URL.

    Args:
        url: e.g. https://polymarket.com/ru/event/ethereum-above-on-september-9-2026

    Returns:
        Event slug string.

    Raises:
        ValueError: If slug cannot be parsed.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("URL is empty")
    parsed = urlparse(raw)
    path = parsed.path or raw
    match = _EVENT_PATH.search(path)
    if not match:
        raise ValueError("URL must contain /event/<slug>")
    slug = match.group(1).strip().rstrip("/")
    if not slug:
        raise ValueError("Event slug is empty")
    return slug
