from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Iterable, Optional

from .models import BatteryMetric


def _to_utc_aware(dt: datetime) -> datetime:
    """
    Normalize datetimes so comparisons never fail.
    - If naive: assume UTC
    - If aware: convert to UTC
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class MetricsRingBuffer:
    def __init__(self, maxlen: int = 5_000) -> None:
        self._lock = threading.Lock()
        self._buf: Deque[BatteryMetric] = deque(maxlen=maxlen)

    def append(self, metric: BatteryMetric) -> None:
        with self._lock:
            self._buf.append(metric)

    def extend(self, metrics: Iterable[BatteryMetric]) -> None:
        with self._lock:
            for m in metrics:
                self._buf.append(m)

    def latest(self, limit: int = 200) -> list[BatteryMetric]:
        if limit <= 0:
            return []
        with self._lock:
            snap = list(self._buf)
        return snap[-limit:]

    def since(self, ts: Optional[datetime], limit: int = 1_000) -> list[BatteryMetric]:
        if limit <= 0:
            return []
        with self._lock:
            snap = list(self._buf)
        if ts is None:
            return snap[-limit:]
        ts_n = _to_utc_aware(ts)
        out: list[BatteryMetric] = []
        for m in snap:
            try:
                if _to_utc_aware(m.ts) > ts_n:
                    out.append(m)
            except Exception:
                # If a row has an invalid timestamp, skip it rather than breaking the whole endpoint.
                continue
        if len(out) > limit:
            out = out[-limit:]
        return out

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)

