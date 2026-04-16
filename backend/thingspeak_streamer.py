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
DEFAULT_BATTERY_CHANNEL_ID = 3337776


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


def _device_channel_id(device_id: str) -> Optional[int]:
    """
    device_id is usually "thingspeak:<channel_id>".
    Returns channel_id int when parseable, else None.
    """
    if not device_id.startswith("thingspeak:"):
        return None
    raw = device_id.split(":", 1)[1].strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _is_battery_profile(device_id: str) -> bool:
    """Battery mapping default for channel 3337776 (can be extended later)."""
    return _device_channel_id(device_id) == DEFAULT_BATTERY_CHANNEL_ID


def feed_to_metric(feed: dict, device_id: str) -> BatteryMetric:
    """Map ThingSpeak fields to telemetry.

    If any field contains BMS-style key=value telemetry (V1=…), parse it and fill battery metrics.
    Otherwise:
      - Battery profile (channel 3337776): field1..4 → V1..V4, field5 → I(A), field6 → T(°C), field7 → SOC(%)
      - Default mapping: 1=temp, 2=humidity, 3=TDS, 4=pH, 5=water quality index.
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

    # Battery numeric-field mapping (when the channel publishes each metric in its own field).
    if _is_battery_profile(device_id):
        v1 = _field_float(feed, "field1")
        v2 = _field_float(feed, "field2")
        v3 = _field_float(feed, "field3")
        v4 = _field_float(feed, "field4")
        cell_voltages: dict[str, float] = {}
        for k, v in (("V1", v1), ("V2", v2), ("V3", v3), ("V4", v4)):
            if v is not None:
                cell_voltages[k] = v
        pack_v = sum(cell_voltages.values()) if cell_voltages else (_field_float(feed, "field1") or 0.0)
        current_a = _field_float(feed, "field5") or 0.0
        temperature_c = _field_float(feed, "field6") or 0.0
        soc_pct = _field_float(feed, "field7")
        raw_line = ",".join(
            [
                f"V1={v1}" if v1 is not None else "",
                f"V2={v2}" if v2 is not None else "",
                f"V3={v3}" if v3 is not None else "",
                f"V4={v4}" if v4 is not None else "",
                f"I={current_a}" if current_a else "",
                f"T={temperature_c}" if temperature_c else "",
                f"SOC={soc_pct}" if soc_pct is not None else "",
            ]
        ).replace(",,", ",").strip(",")
        return BatteryMetric(
            ts=_parse_ts(feed["created_at"]),
            device_id=device_id,
            voltage_v=float(pack_v),
            current_a=float(current_a),
            temperature_c=float(temperature_c),
            soc_pct=float(soc_pct) if soc_pct is not None else None,
            cell_voltages=cell_voltages or None,
            humidity_pct=None,
            tds_ppm=None,
            ph=None,
            water_quality_index=None,
            raw_line=raw_line or raw_default,
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

        self._last_error: Optional[str] = None
        self._last_feed_count: int = 0
        self._polls_succeeded: int = 0
        self._polls_failed: int = 0

    def diagnostics(self) -> dict:
        """Expose to GET /status so the UI can explain empty charts."""
        with self._lock:
            return {
                "last_error": self._last_error,
                "last_feed_count": self._last_feed_count,
                "polls_succeeded": self._polls_succeeded,
                "polls_failed": self._polls_failed,
            }

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
        """GET feeds.json; raises on HTTP errors, JSON errors, or ThingSpeak `error` payloads."""
        url = THINGSPEAK_FEEDS_URL.format(channel_id=self.channel_id)
        r = requests.get(
            url,
            params={"api_key": self.api_key, "results": results},
            timeout=30,
        )
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            snippet = (e.response.text if e.response is not None else "")[:240].replace("\n", " ")
            code = e.response.status_code if e.response is not None else "?"
            raise RuntimeError(
                f"ThingSpeak HTTP {code} for channel {self.channel_id}: {snippet!r}"
            ) from e
        try:
            data = r.json()
        except ValueError as e:
            snippet = (r.text or "")[:240].replace("\n", " ")
            raise RuntimeError(f"ThingSpeak response is not JSON ({snippet!r})") from e
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(str(data["error"]))
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected ThingSpeak JSON payload: {data!r}")
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

    def _record_poll_ok(self, feeds: list[dict]) -> None:
        with self._lock:
            self._last_error = None
            self._last_feed_count = len(feeds)
            self._polls_succeeded += 1

    def _record_poll_err(self, exc: BaseException) -> None:
        msg = str(exc).strip() or repr(exc)
        if len(msg) > 500:
            msg = msg[:497] + "…"
        with self._lock:
            self._last_error = msg
            self._polls_failed += 1
        log.warning("ThingSpeak poll failed: %s", exc)

    def _run(self, on_metric: Callable[[BatteryMetric], None]) -> None:
        self._running.set()
        try:
            feeds = self._fetch_feeds(self.initial_results)
            self._record_poll_ok(feeds)
            self._emit_new(feeds, on_metric, initial=True)
        except Exception as e:
            self._record_poll_err(e)
            log.warning("ThingSpeak initial fetch failed: %s", e)

        while not self._stop.is_set():
            try:
                feeds = self._fetch_feeds(min(100, max(20, self.initial_results)))
                self._record_poll_ok(feeds)
                self._emit_new(feeds, on_metric, initial=False)
            except Exception as e:
                self._record_poll_err(e)
            self._stop.wait(self.poll_interval_sec)
