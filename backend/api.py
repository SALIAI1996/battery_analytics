from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

log = logging.getLogger(__name__)
from fastapi.middleware.cors import CORSMiddleware

from .bluetooth_pair import inquiry as bt_inquiry, pair_and_connect as bt_pair
from .hc05_serial import list_serial_ports
from .models import (
    ConnectRequest, ConnectResponse, DiscoveredDevice,
    LatestResponse, PairRequest, PairResponse, SerialPortInfo, StatusResponse,
    TerminalSendRequest,
)
from .state import STATE

app = FastAPI(title="Battery Analytics Backend", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/serial-ports", response_model=list[SerialPortInfo])
def serial_ports() -> list[SerialPortInfo]:
    """List all serial ports visible to the OS (paired HC-05 will appear here)."""
    return [SerialPortInfo(**p) for p in list_serial_ports()]


@app.get("/devices", response_model=list[DiscoveredDevice])
def devices(include_sim: bool = True) -> list[DiscoveredDevice]:
    """List available devices: serial ports + simulation."""
    found: list[DiscoveredDevice] = []

    if include_sim:
        found.append(
            DiscoveredDevice(
                device_id="SIM_BATTERY_001",
                name="Simulated Battery (4 cells)",
                is_simulated=True,
            )
        )

    for p in list_serial_ports():
        port = p["port"] or ""
        desc = p.get("description") or ""
        mfr = p.get("manufacturer") or ""
        label = f"{desc} ({mfr})" if mfr else desc
        found.append(
            DiscoveredDevice(
                device_id=port,
                name=label or port,
                port=port,
                is_simulated=False,
            )
        )

    return found


@app.get("/bluetooth-scan")
def bluetooth_scan(duration: int = Query(default=8, ge=3, le=30)) -> list[dict]:
    """Scan for nearby Bluetooth devices (takes several seconds)."""
    try:
        return bt_inquiry(duration=duration)
    except Exception as e:
        log.warning("Bluetooth scan failed: %s", e)
        return []


@app.post("/pair-bluetooth", response_model=PairResponse)
def pair_bluetooth(req: PairRequest) -> PairResponse:
    """Pair with an HC-05 by MAC address, connect, and discover the serial port."""
    try:
        result = bt_pair(mac_raw=req.mac_address, pin=req.pin)
        return PairResponse(
            mac=result.mac,
            already_paired=result.already_paired,
            paired=result.paired,
            connected=result.connected,
            serial_port=result.serial_port,
            message=result.message,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/connect", response_model=ConnectResponse)
def connect(req: ConnectRequest) -> ConnectResponse:
    if req.simulated or req.device_id.startswith("SIM_"):
        STATE.connect_sim(device_id=req.device_id)
        return ConnectResponse(device_id=req.device_id, connected=True, message="Connected (simulation).")

    try:
        STATE.connect_serial(port=req.device_id, baudrate=req.baudrate)
        return ConnectResponse(
            device_id=req.device_id,
            connected=True,
            message=f"Opening serial port {req.device_id} at {req.baudrate} baud…",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/disconnect")
def disconnect() -> dict:
    STATE.stop_all()
    return {"ok": True}


@app.get("/terminal/log")
def terminal_log(
    since_id: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict:
    """Incremental RX/TX log (Arduino Bluetooth Controller–style stream)."""
    if STATE.mode != "serial" or STATE.serial is None:
        return {"ok": False, "lines": [], "last_id": since_id, "message": "Not connected to serial."}
    lines = STATE.serial.terminal_since(since_id, limit)
    last_id = since_id
    for e in lines:
        last_id = max(last_id, int(e["id"]))
    return {"ok": True, "lines": lines, "last_id": last_id, "message": ""}


@app.post("/terminal/send")
def terminal_send(req: TerminalSendRequest) -> dict:
    """Send bytes to the active HC-05 / serial port (TX)."""
    if STATE.mode != "serial" or STATE.serial is None:
        raise HTTPException(status_code=400, detail="Not connected to serial.")
    payload = req.text.encode("utf-8", errors="replace")
    if req.append_crlf:
        payload += b"\r\n"
    ok, msg = STATE.serial.write_bytes(payload)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@app.post("/terminal/clear")
def terminal_clear() -> dict:
    """Clear in-memory terminal log (UI buffer should reset too)."""
    if STATE.mode == "serial" and STATE.serial is not None:
        STATE.serial.clear_terminal()
    return {"ok": True}


@app.get("/status", response_model=StatusResponse)
def status() -> StatusResponse:
    s = STATE.status()
    return StatusResponse(**s)


def _parse_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


@app.get("/serial-test")
def serial_test(
    port: str = Query(description="Serial port path, e.g. /dev/tty.HC-05 or COM3"),
    baudrate: int = Query(default=9600),
    duration: int = Query(default=5, ge=1, le=30, description="How many seconds to listen"),
) -> dict:
    """
    Open a serial port for a few seconds and return whatever raw bytes come in.
    Useful for diagnosing whether the HC-05 / MCU is actually sending data.
    """
    import serial
    import time

    lines: list[str] = []
    raw_bytes = 0
    try:
        ser = serial.Serial(port, baudrate, timeout=1.0)
        ser.reset_input_buffer()
        deadline = time.time() + duration
        while time.time() < deadline:
            chunk = ser.read(ser.in_waiting or 1)
            if chunk:
                raw_bytes += len(chunk)
                text = chunk.decode(errors="replace")
                for line in text.splitlines():
                    line = line.strip()
                    if line:
                        lines.append(line)
        ser.close()
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "port": port,
            "baudrate": baudrate,
            "raw_bytes": 0,
            "lines": [],
        }

    return {
        "ok": True,
        "port": port,
        "baudrate": baudrate,
        "duration_sec": duration,
        "raw_bytes": raw_bytes,
        "lines": lines[-50:],
        "message": (
            f"Received {raw_bytes} bytes, {len(lines)} lines in {duration}s"
            if raw_bytes > 0
            else f"No data received in {duration}s. Is your MCU sending data to the HC-05?"
        ),
    }


@app.get("/serial-send-test")
def serial_send_test(
    port: str = Query(description="Serial port path"),
    baudrate: int = Query(default=9600),
    message: str = Query(default="AT\r\n", description="Text to send"),
    wait: int = Query(default=3, ge=1, le=10, description="Seconds to wait for reply"),
) -> dict:
    """Send text to serial port and capture any response. Used to diagnose HC-05 mode."""
    import serial
    import time

    lines: list[str] = []
    raw_bytes = 0
    try:
        ser = serial.Serial(port, baudrate, timeout=1.0)
        ser.reset_input_buffer()
        ser.write(message.encode())
        ser.flush()

        deadline = time.time() + wait
        while time.time() < deadline:
            chunk = ser.read(ser.in_waiting or 1)
            if chunk:
                raw_bytes += len(chunk)
                for line in chunk.decode(errors="replace").splitlines():
                    line = line.strip()
                    if line:
                        lines.append(line)
        ser.close()
    except Exception as e:
        return {"ok": False, "error": str(e), "raw_bytes": 0, "lines": []}

    return {
        "ok": True,
        "port": port,
        "baudrate": baudrate,
        "sent": repr(message),
        "raw_bytes": raw_bytes,
        "lines": lines,
        "message": (
            f"Sent {repr(message)}, received {raw_bytes} bytes"
            if raw_bytes > 0
            else f"Sent {repr(message)}, no response in {wait}s"
        ),
    }


@app.get("/metrics/latest", response_model=LatestResponse)
def latest(
    since: Optional[str] = Query(default=None, description="ISO8601 timestamp"),
    limit: int = Query(default=500, ge=1, le=5000),
) -> LatestResponse:
    s = STATE.status()
    device_id = s["active_device_id"]
    if not device_id:
        raise HTTPException(status_code=400, detail="No active device. Connect first.")
    ts = _parse_ts(since)
    pts = STATE.latest_since(ts=ts, limit=limit)
    return LatestResponse(device_id=device_id, points=pts)
