from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional

from .hc05_serial import HC05SerialStreamer
from .models import BatteryMetric
from .ring_buffer import MetricsRingBuffer
from .sim_device import SimulatedBatteryStreamer
from .thingspeak_streamer import ThingSpeakStreamer


class AppState:
    def __init__(self) -> None:
        self._lock = threading.Lock()

        self.serial: HC05SerialStreamer | None = None
        self.sim: SimulatedBatteryStreamer | None = None
        self.thingspeak: ThingSpeakStreamer | None = None

        self.buffer = MetricsRingBuffer(maxlen=10_000)

        self.mode: str = "none"  # "serial" | "sim" | "thingspeak" | "none"
        self.active_device_id: str | None = None

    def _on_metric(self, m: BatteryMetric) -> None:
        self.buffer.append(m)

    def stop_all(self) -> None:
        with self._lock:
            if self.serial:
                self.serial.stop()
                self.serial = None
            if self.sim:
                self.sim.stop()
                self.sim = None
            if self.thingspeak:
                self.thingspeak.stop()
                self.thingspeak = None
            self.mode = "none"
            self.active_device_id = None

    def connect_sim(self, device_id: str) -> None:
        self.stop_all()
        with self._lock:
            self.buffer.clear()
            self.sim = SimulatedBatteryStreamer(device_id=device_id, hz=8.0)
            self.sim.start(self._on_metric)
            self.mode = "sim"
            self.active_device_id = device_id

    def connect_serial(self, port: str, baudrate: int = 9600) -> None:
        self.stop_all()
        with self._lock:
            self.buffer.clear()
            self.serial = HC05SerialStreamer(port=port, baudrate=baudrate)
            self.serial.start(self._on_metric)
            self.mode = "serial"
            self.active_device_id = port

    def connect_thingspeak(
        self,
        channel_id: int,
        read_api_key: str,
        *,
        poll_interval_sec: float = 15.0,
        initial_results: int = 500,
    ) -> None:
        self.stop_all()
        with self._lock:
            self.buffer.clear()
            self.thingspeak = ThingSpeakStreamer(
                channel_id,
                read_api_key,
                poll_interval_sec=poll_interval_sec,
                initial_results=initial_results,
            )
            self.thingspeak.start(self._on_metric)
            self.mode = "thingspeak"
            self.active_device_id = self.thingspeak.device_id

    def status(self) -> dict:
        with self._lock:
            if self.mode == "sim":
                connected = bool(self.sim and self.sim.running)
                streaming = connected
            elif self.mode == "serial":
                connected = bool(self.serial and self.serial.connected)
                streaming = bool(self.serial and self.serial.streaming)
            elif self.mode == "thingspeak":
                connected = bool(self.thingspeak and self.thingspeak.running)
                streaming = connected
            else:
                connected = False
                streaming = False
            return {
                "active_device_id": self.active_device_id,
                "connected": connected,
                "streaming": streaming,
                "mode": self.mode,
            }

    def latest_since(self, ts: Optional[datetime], limit: int = 500) -> list[BatteryMetric]:
        return self.buffer.since(ts=ts, limit=limit)


STATE = AppState()
