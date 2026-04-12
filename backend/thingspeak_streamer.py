from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

import requests

from .models import BatteryMetric
from .sc05_uart import parse_sc05_line

log = logging.getLogger(__name__)

THINGSPEAK_FEEDS_URL = "https://api.thingspeak.com/channels/{channel_id}/feeds.json"


def _parse_ts(created_at: str) -> datetime:
    s = created_at.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _field_float(feed: dict, key: str) -> Optional[float]:
    v = feed.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _looks_like_bms_line(s: str) -> bool:
    """Detect BMS-style telemetry (e.g. V1=3.7,...,I=1.2A,T=30C,SOC=75%) in a ThingSpeak field."""
    return bool(re.search(r"\bV1\s*=", s, re.I) or re.search(r"\bV1\s*:", s, re.I))


def feed_to_metric(feed: dict, device_id: str) -> BatteryMetric:
    """Map ThingSpeak fields to telemetry.

    If any field contains BMS-style key=value telemetry (V1=…), parse it and fill battery metrics.
    Otherwise default mapping: 1=temp, 2=humidity, 3=TDS, 4=pH, 5=water quality index.
    """
    eid = feed.get("entry_id")
    raw_default = f"ThingSpeak entry_id={eid}" if eid is not None else "ThingSpeak"

    for i in range(1, 9):
        key = f"field{i}"
        raw = feed.get(key)
        if raw is None or raw == "":
            continue
        s = str(raw).strip()
        if not _looks_like_bms_line(s):
            continue
        parsed = parse_sc05_line(s)
        if parsed is None:
            continue
        if not parsed.cell_voltages and parsed.voltage_v <= 0 and parsed.current_a == 0:
            continue
        raw_line = s[:500] if len(s) > 500 else s
        return BatteryMetric(
            ts=_parse_ts(feed["created_at"]),
            device_id=device_id,
            voltage_v=parsed.voltage_v,
            current_a=parsed.current_a,
            temperature_c=parsed.temperature_c,
            soc_pct=parsed.soc_pct,
            cell_voltages=parsed.cell_voltages,
            humidity_pct=None,
            tds_ppm=None,
            ph=None,
            water_quality_index=None,
            raw_line=raw_line,
            source="thingspeak",
        )

    return BatteryMetric(
        ts=_parse_ts(feed["created_at"]),
        device_id=device_id,
        voltage_v=0.0,
        current_a=0.0,
        temperature_c=_field_float(feed, "field1") or 0.0,
        soc_pct=None,
        cell_voltages=None,
        humidity_pct=_field_float(feed, "field2"),
        tds_ppm=_field_float(feed, "field3"),
        ph=_field_float(feed, "field4"),
        water_quality_index=_field_float(feed, "field5"),
        raw_line=raw_default,
        source="thingspeak",
    )


class ThingSpeakStreamer:
    """
    Polls ThingSpeak channel feeds and pushes BatteryMetric rows into the app buffer.
    """

    def __init__(
        self,
        channel_id: int,
        api_key: str,
        *,
        poll_interval_sec: float = 15.0,
        initial_results: int = 500,
    ) -> None:
        self.channel_id = int(channel_id)
        self.api_key = api_key
        self.poll_interval_sec = max(5.0, float(poll_interval_sec))
        self.initial_results = max(1, min(8000, int(initial_results)))
        self.device_id = f"thingspeak:{self.channel_id}"

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._running = threading.Event()
        self._last_entry_id: int = 0
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def start(self, on_metric: Callable[[BatteryMetric], None]) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(on_metric,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._running.clear()

    def _fetch_feeds(self, results: int) -> list[dict]:
        url = THINGSPEAK_FEEDS_URL.format(channel_id=self.channel_id)
        r = requests.get(
            url,
            params={"api_key": self.api_key, "results": results},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        feeds = data.get("feeds") or []
        return feeds if isinstance(feeds, list) else []

    def _emit_new(
        self,
        feeds: list[dict],
        on_metric: Callable[[BatteryMetric], None],
        *,
        initial: bool,
    ) -> None:
        # Chronological order
        try:
            feeds = sorted(feeds, key=lambda f: int(f.get("entry_id") or 0))
        except Exception:
            pass

        with self._lock:
            last = self._last_entry_id

        for feed in feeds:
            eid = feed.get("entry_id")
            try:
                eid_int = int(eid) if eid is not None else 0
            except (TypeError, ValueError):
                eid_int = 0
            if not initial and eid_int > 0 and eid_int <= last:
                continue
            if "created_at" not in feed:
                continue
            try:
                m = feed_to_metric(feed, self.device_id)
            except Exception as ex:
                log.warning("ThingSpeak feed parse skip: %s", ex)
                continue
            on_metric(m)
            with self._lock:
                if eid_int > self._last_entry_id:
                    self._last_entry_id = eid_int

    def _run(self, on_metric: Callable[[BatteryMetric], None]) -> None:
        self._running.set()
        try:
            feeds = self._fetch_feeds(self.initial_results)
            self._emit_new(feeds, on_metric, initial=True)
        except Exception as e:
            log.warning("ThingSpeak initial fetch failed: %s", e)

        while not self._stop.is_set():
            try:
                feeds = self._fetch_feeds(min(100, max(20, self.initial_results)))
                self._emit_new(feeds, on_metric, initial=False)
            except Exception as e:
                log.warning("ThingSpeak poll failed: %s", e)
            self._stop.wait(self.poll_interval_sec)
