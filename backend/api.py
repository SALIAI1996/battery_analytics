from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load repo-root .env before any os.environ reads
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, HTTPException, Query

log = logging.getLogger(__name__)
from fastapi.middleware.cors import CORSMiddleware

from .serial_streamer import list_serial_ports
from .models import (
    ConnectRequest, ConnectResponse, DiscoveredDevice,
    LatestResponse, SerialPortInfo, StatusResponse,
    TerminalSendRequest, ThingSpeakConnectRequest,
)
from .state import STATE

app = FastAPI(title="Environmental Analytics Backend", version="0.3.0")


def _cors_origins() -> list[str]:
    raw = (os.environ.get("CORS_ORIGINS") or "").strip()
    if not raw or raw == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


# Browsers reject credentialed CORS with wildcard origin; this API uses cookie-less fetch.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict:
    """Visiting the service root in a browser shows this instead of 404."""
    return {
        "service": "Environmental Analytics API",
        "docs": "/docs",
        "health": "/health",
        "hint": "The React app calls /status, /connect-thingspeak, etc. — not GET /",
    }


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/serial-ports", response_model=list[SerialPortInfo])
def serial_ports() -> list[SerialPortInfo]:
    """List serial ports visible to the OS (e.g. USB–UART adapters)."""
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


def _resolve_thingspeak_key(req: ThingSpeakConnectRequest) -> str:
    key = (req.read_api_key or "").strip()
    if key:
        return key
    env_key = (os.environ.get("THINGSPEAK_READ_API_KEY") or "").strip()
    if env_key:
        return env_key
    raise HTTPException(
        status_code=422,
        detail="ThingSpeak read API key required: set read_api_key in the request or THINGSPEAK_READ_API_KEY in the environment.",
    )


@app.post("/connect-thingspeak", response_model=ConnectResponse)
def connect_thingspeak(req: ThingSpeakConnectRequest) -> ConnectResponse:
    """Subscribe to a ThingSpeak channel feed (replaces serial as the active data source)."""
    key = _resolve_thingspeak_key(req)
    try:
        STATE.connect_thingspeak(
            req.channel_id,
            key,
            poll_interval_sec=req.poll_interval_sec,
            initial_results=req.initial_results,
        )
        dev = STATE.active_device_id or f"thingspeak:{req.channel_id}"
        return ConnectResponse(
            device_id=dev,
            connected=True,
            message=f"ThingSpeak channel {req.channel_id}: loading up to {req.initial_results} points, then polling every {req.poll_interval_sec:.0f}s.",
        )
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
    """Incremental RX/TX log for the active serial session."""
    if STATE.mode != "serial" or STATE.serial is None:
        return {"ok": False, "lines": [], "last_id": since_id, "message": "Not connected to serial."}
    lines = STATE.serial.terminal_since(since_id, limit)
    last_id = since_id
    for e in lines:
        last_id = max(last_id, int(e["id"]))
    return {"ok": True, "lines": lines, "last_id": last_id, "message": ""}


@app.post("/terminal/send")
def terminal_send(req: TerminalSendRequest) -> dict:
    """Send bytes to the active serial port (TX)."""
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
    port: str = Query(description="Serial port path, e.g. /dev/tty.usbserial-* or COM3"),
    baudrate: int = Query(default=9600),
    duration: int = Query(default=5, ge=1, le=30, description="How many seconds to listen"),
) -> dict:
    """
    Open a serial port for a few seconds and return whatever raw bytes come in.
    Useful for diagnosing whether a device on the serial port is sending data.
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
            else f"No data received in {duration}s. Is the device transmitting on this port?"
        ),
    }


@app.get("/serial-send-test")
def serial_send_test(
    port: str = Query(description="Serial port path"),
    baudrate: int = Query(default=9600),
    message: str = Query(default="AT\r\n", description="Text to send"),
    wait: int = Query(default=3, ge=1, le=10, description="Seconds to wait for reply"),
) -> dict:
    """Send text to serial port and capture any response."""
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
