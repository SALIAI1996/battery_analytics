"""HTTP helpers for ThingSpeak public API (feeds, fields, channel status)."""

from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

THINGSPEAK_BASE = "https://api.thingspeak.com/channels"


def fetch_feeds_json(channel_id: int, api_key: str, *, results: int = 100) -> dict[str, Any]:
    url = f"{THINGSPEAK_BASE}/{channel_id}/feeds.json"
    r = requests.get(
        url,
        params={"api_key": api_key, "results": max(1, min(8000, results))},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_field_json(channel_id: int, field: int, api_key: str, *, results: int = 100) -> dict[str, Any]:
    if field < 1 or field > 8:
        raise ValueError("field must be 1–8")
    url = f"{THINGSPEAK_BASE}/{channel_id}/fields/{field}.json"
    r = requests.get(
        url,
        params={"api_key": api_key, "results": max(1, min(8000, results))},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_channel_status_json(channel_id: int, api_key: str) -> dict[str, Any]:
    url = f"{THINGSPEAK_BASE}/{channel_id}/status.json"
    r = requests.get(url, params={"api_key": api_key}, timeout=30)
    r.raise_for_status()
    return r.json()
