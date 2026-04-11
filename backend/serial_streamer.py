"""
Serial port streamer for UART telemetry (e.g. USB–UART adapter to a microcontroller).

Opens a serial device and reads ASCII lines continuously for battery-metric parsing.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Optional

import serial
import serial.tools.list_ports

from .models import BatteryMetric
from .sc05_uart import ParsedBattery, parse_sc05_line

log = logging.getLogger(__name__)


def list_serial_ports() -> list[dict[str, str | None]]:
    """Return all serial ports visible to the OS, with metadata."""
    ports = []
    for p in serial.tools.list_ports.comports():
        ports.append({
            "port": p.device,
            "description": p.description,
            "hwid": p.hwid,
            "manufacturer": p.manufacturer,
        })
    ports.sort(key=lambda x: x["port"] or "")
    return ports


class SerialTelemetryStreamer:
    """
    Opens a serial port and reads lines continuously.
    Each line is parsed for battery metrics and pushed via the on_metric callback.
    """

    def __init__(self, port: str, baudrate: int = 9600) -> None:
        self.port = port
        self.baudrate = baudrate
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._streaming = threading.Event()
        # Live RX/TX log for debugging
        self._terminal_lock = threading.Lock()
        self._terminal: deque[dict[str, object]] = deque(maxlen=3_000)
        self._terminal_seq = 0
        self._ser_lock = threading.Lock()
        self._ser: serial.Serial | None = None

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def streaming(self) -> bool:
        return self._streaming.is_set()

    def start(self, on_metric: Callable[[BatteryMetric], None]) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(on_metric,), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._ser_lock:
            self._ser = None
        self._connected.clear()
        self._streaming.clear()

    def clear_terminal(self) -> None:
        with self._terminal_lock:
            self._terminal.clear()
            self._terminal_seq = 0

    def _append_terminal(self, direction: str, text: str) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "dir": direction,
            "text": text[:8_000],
        }
        with self._terminal_lock:
            self._terminal_seq += 1
            entry["id"] = self._terminal_seq
            self._terminal.append(entry)

    def terminal_since(self, since_id: int, limit: int = 500) -> list[dict[str, object]]:
        with self._terminal_lock:
            out = [e for e in self._terminal if int(e["id"]) > since_id]
        if len(out) > limit:
            out = out[-limit:]
        return out

    def write_bytes(self, data: bytes) -> tuple[bool, str]:
        """Send data on TX. Thread-safe."""
        if not data:
            return False, "Empty payload"
        with self._ser_lock:
            ser = self._ser
            if ser is None or not ser.is_open:
                return False, "Serial port not open"
            try:
                ser.write(data)
                ser.flush()
            except (serial.SerialException, OSError) as exc:
                return False, str(exc)
        # Log TX as readable string
        disp = data.decode(errors="replace").replace("\r", "␍").replace("\n", "␊")
        self._append_terminal("tx", disp)
        return True, f"Sent {len(data)} bytes"

    def _run(self, on_metric: Callable[[BatteryMetric], None]) -> None:
        backoff = 0.5
        while not self._stop.is_set():
            ser: serial.Serial | None = None
            try:
                log.info("Opening serial port %s at %d baud", self.port, self.baudrate)

                # On macOS, "Resource busy" can happen if the port was recently
                # closed. Retry open a few times with small delays.
                for attempt in range(5):
                    if self._stop.is_set():
                        return
                    try:
                        ser = serial.Serial(
                            self.port,
                            self.baudrate,
                            timeout=2.0,
                            bytesize=serial.EIGHTBITS,
                            parity=serial.PARITY_NONE,
                            stopbits=serial.STOPBITS_ONE,
                            xonxoff=False,
                            rtscts=False,
                            dsrdtr=False,
                        )
                        break
                    except (serial.SerialException, OSError) as exc:
                        if attempt < 4:
                            log.info("Port open attempt %d failed (%s), retrying…", attempt + 1, exc)
                            time.sleep(1.0)
                        else:
                            raise

                if ser is None:
                    continue

                with self._ser_lock:
                    self._ser = ser

                self._connected.set()
                self._streaming.set()
                backoff = 0.5
                log.info("Serial port %s opened successfully", self.port)

                # Flush any stale bytes
                ser.reset_input_buffer()

                idle_count = 0
                while not self._stop.is_set():
                    raw = ser.readline()
                    # Some firmware sends without \n; drain waiting bytes
                    if not raw and ser.in_waiting:
                        raw = ser.read(min(ser.in_waiting, 1024))
                    if not raw:
                        idle_count += 1
                        # After 30s of no data, check port is still alive
                        if idle_count > 15:
                            idle_count = 0
                            if not ser.is_open:
                                log.warning("Port %s closed unexpectedly", self.port)
                                break
                        continue

                    idle_count = 0
                    line = raw.decode(errors="replace").rstrip("\r\n")
                    if not line:
                        continue

                    self._append_terminal("rx", line)
                    log.info("UART rx: %r", line)
                    parsed: ParsedBattery | None = parse_sc05_line(line)
                    if parsed is None:
                        log.info("Unparseable (storing raw): %r", line)
                        on_metric(
                            BatteryMetric(
                                ts=datetime.now(timezone.utc),
                                device_id=self.port,
                                voltage_v=0.0,
                                current_a=0.0,
                                temperature_c=0.0,
                                raw_line=line,
                                source="serial",
                            )
                        )
                        continue

                    on_metric(
                        BatteryMetric(
                            ts=datetime.now(timezone.utc),
                            device_id=self.port,
                            voltage_v=parsed.voltage_v,
                            current_a=parsed.current_a,
                            temperature_c=parsed.temperature_c,
                            soc_pct=parsed.soc_pct,
                            cell_voltages=parsed.cell_voltages,
                            raw_line=line,
                            source="serial",
                        )
                    )

            except serial.SerialException as exc:
                log.warning("Serial error on %s: %s", self.port, exc)
            except OSError as exc:
                log.warning("OS error on %s: %s", self.port, exc)
            finally:
                with self._ser_lock:
                    self._ser = None
                if ser and ser.is_open:
                    try:
                        ser.close()
                    except Exception:
                        pass
                self._connected.clear()
                self._streaming.clear()

            if self._stop.is_set():
                break
            log.info("Reconnecting to %s in %.1fs…", self.port, backoff)
            time.sleep(backoff)
            backoff = min(10.0, backoff * 1.8)
