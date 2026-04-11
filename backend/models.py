from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class BatteryMetric(BaseModel):
    ts: datetime = Field(description="UTC timestamp")
    device_id: str
    voltage_v: float = Field(description="Pack / total voltage")
    current_a: float = 0.0
    temperature_c: float = 0.0
    soc_pct: Optional[float] = None
    cell_voltages: Optional[dict[str, float]] = Field(
        default=None,
        description='Per-cell voltages, e.g. {"V1": 3.65, "V2": 3.64, ...}',
    )
    raw_line: Optional[str] = Field(default=None, description="Raw UART line for debugging")
    source: Literal["ble", "serial", "sim"] = "serial"


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
    mode: Literal["serial", "sim", "none"]


class PairRequest(BaseModel):
    mac_address: str = Field(description="HC-05 MAC address, e.g. 00:23:09:01:5A:78")
    pin: str = "1234"


class PairResponse(BaseModel):
    mac: str
    already_paired: bool
    paired: bool
    connected: bool
    serial_port: str | None
    message: str


class LatestResponse(BaseModel):
    device_id: str
    points: list[BatteryMetric]


class TerminalSendRequest(BaseModel):
    text: str = ""
    append_crlf: bool = Field(
        default=True,
        description="Append \\r\\n after text (Arduino / HC-05 default).",
    )
