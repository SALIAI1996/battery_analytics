from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class BatteryMetric(BaseModel):
    ts: datetime = Field(description="UTC timestamp")
    device_id: str
    voltage_v: float = Field(description="Pack / total voltage (0 when source is ThingSpeak)")
    current_a: float = 0.0
    temperature_c: float = 0.0
    soc_pct: Optional[float] = None
    cell_voltages: Optional[dict[str, float]] = Field(
        default=None,
        description='Per-cell voltages, e.g. {"V1": 3.65, "V2": 3.64, ...}',
    )
    humidity_pct: Optional[float] = Field(default=None, description="Relative humidity % (ThingSpeak field2)")
    tds_ppm: Optional[float] = Field(default=None, description="TDS (ThingSpeak field3)")
    ph: Optional[float] = Field(default=None, description="pH (ThingSpeak field4)")
    water_quality_index: Optional[float] = Field(
        default=None,
        description="Optional water quality score (ThingSpeak field5 if present)",
    )
    raw_line: Optional[str] = Field(default=None, description="Raw UART line for debugging")
    source: Literal["serial", "sim", "thingspeak"] = "serial"


class SerialPortInfo(BaseModel):
    port: str
    description: str | None = None
    hwid: str | None = None
    manufacturer: str | None = None


class DiscoveredDevice(BaseModel):
    device_id: str
    name: str | None = None
    port: str | None = None
    is_simulated: bool = False


class ConnectRequest(BaseModel):
    device_id: str
    simulated: bool = False
    baudrate: int = 9600


class ConnectResponse(BaseModel):
    device_id: str
    connected: bool
    message: str


class StatusResponse(BaseModel):
    active_device_id: str | None
    connected: bool
    streaming: bool
    mode: Literal["serial", "sim", "none", "thingspeak"]


class ThingSpeakConnectRequest(BaseModel):
    channel_id: int = Field(default=3337776, description="ThingSpeak channel ID")
    read_api_key: str = Field(
        default="",
        description="Read API key; if empty, uses env THINGSPEAK_READ_API_KEY",
    )
    poll_interval_sec: float = Field(default=15.0, ge=5.0, le=3600.0)
    initial_results: int = Field(default=500, ge=1, le=8000, description="How many past points to load on connect")


class LatestResponse(BaseModel):
    device_id: str
    points: list[BatteryMetric]


class TerminalSendRequest(BaseModel):
    text: str = ""
    append_crlf: bool = Field(
        default=True,
        description="Append \\r\\n after text (common for UART).",
    )
