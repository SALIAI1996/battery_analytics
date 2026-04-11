from __future__ import annotations

import math
import random
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from .models import BatteryMetric


class SimulatedBatteryStreamer:
    """
    Generates realistic-ish battery telemetry at a fixed cadence.
    """

    def __init__(self, device_id: str, hz: float = 5.0) -> None:
        self.device_id = device_id
        self.hz = max(0.5, float(hz))
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._running = threading.Event()

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

    def _run(self, on_metric: Callable[[BatteryMetric], None]) -> None:
        self._running.set()
        t0 = time.time()
        soc = 86.0
        while not self._stop.is_set():
            t = time.time() - t0
            # Simulate gentle load variations
            current = 8.0 * math.sin(t / 6.5) + 1.5 * math.sin(t / 1.8) + random.uniform(-0.6, 0.6)
            current = float(max(-25.0, min(25.0, current)))

            # Simplified voltage model
            ocv = 52.0 + (soc / 100.0) * 6.0  # 52V..58V
            voltage = ocv - 0.03 * current + random.uniform(-0.05, 0.05)

            # Temperature rises with load
            temperature = 26.5 + 0.05 * abs(current) + 0.4 * math.sin(t / 20.0) + random.uniform(-0.2, 0.2)

            # SOC drifts slowly
            soc = max(0.0, min(100.0, soc - (abs(current) / 25.0) * (1.0 / (self.hz * 600.0))))

            # Simulate 4 individual cell voltages (pack ÷ ~16 cells, show 4)
            base_cell = voltage / 16.0
            cells = {
                f"V{i+1}": round(base_cell + random.uniform(-0.02, 0.02), 3)
                for i in range(4)
            }

            on_metric(
                BatteryMetric(
                    ts=datetime.now(timezone.utc),
                    device_id=self.device_id,
                    voltage_v=float(voltage),
                    current_a=float(current),
                    temperature_c=float(temperature),
                    soc_pct=float(soc),
                    cell_voltages=cells,
                    source="sim",
                )
            )
            time.sleep(1.0 / self.hz)

