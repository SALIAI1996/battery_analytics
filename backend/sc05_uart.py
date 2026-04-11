"""
UART line parser for battery data from microcontrollers (PIC16F877A, Arduino, etc.)
via HC-05 Bluetooth serial bridge.

Handles multiple data formats:
  - Multi-cell: "V1:3.65,V2:3.64,V3:3.66,V4:3.63,I:2.1,T:28.5"
  - CSV cells:  "3.65,3.64,3.66,3.63"  (all numbers → cell voltages)
  - JSON:       {"V1":3.65,"V2":3.64,"current":2.1,"temp":28.5}
  - Simple CSV: "12.6,2.1,28.5"  (V, I, T)
  - Raw ADC:    "512,745,890,310"  (10-bit ADC values, auto-converted)
  - Single value: "3.65" or "745"
  - Raw hex frames from BMS protocols
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"


def sc05_notify_uuid() -> str:
    return os.environ.get("SC05_NOTIFY_UUID", DEFAULT_NOTIFY_UUID).strip()


@dataclass
class UartLineBuffer:
    buf: bytearray = field(default_factory=bytearray)

    def feed(self, data: bytes) -> list[str]:
        self.buf.extend(data)
        lines: list[str] = []
        while True:
            nl_at: int | None = None
            for i, b in enumerate(self.buf):
                if b in (0x0A, 0x0D):
                    nl_at = i
                    break
            if nl_at is None:
                break
            raw = bytes(self.buf[:nl_at])
            del self.buf[: nl_at + 1]
            # consume \r\n pair
            if self.buf and self.buf[0] in (0x0A, 0x0D):
                del self.buf[:1]
            s = raw.decode(errors="replace").strip()
            if s:
                lines.append(s)
        # Safety: don't let buffer grow unbounded if no newlines arrive
        if len(self.buf) > 4096:
            chunk = self.buf.decode(errors="replace").strip()
            self.buf.clear()
            if chunk:
                lines.append(chunk)
        return lines


@dataclass
class ParsedBattery:
    voltage_v: float = 0.0
    current_a: float = 0.0
    temperature_c: float = 0.0
    soc_pct: float | None = None
    cell_voltages: dict[str, float] | None = None


def parse_sc05_line(line: str) -> ParsedBattery | None:
    """
    Parse a UART line from an SC05/BMS module. Tries multiple formats.
    Returns None only if absolutely nothing parseable is found.
    """
    line = line.strip()
    if not line:
        return None

    # ── 1. JSON ──────────────────────────────────────────────────────────────
    if line.startswith("{"):
        return _parse_json(line)

    # ── 2. Key:value or Key=value pairs ──────────────────────────────────────
    # e.g. "V1:3.65,V2:3.64,V3:3.66,V4:3.63,I:2.1,T:28.5,SOC:87"
    if re.search(r"[A-Za-z]\d*\s*[:=]", line):
        return _parse_kv(line)

    # ── 3. Pure numbers (CSV or space-separated) ─────────────────────────────
    sep = "," if "," in line else None
    parts = line.split(sep) if sep else line.split()
    nums: list[float] = []
    for p in parts:
        p = p.strip()
        try:
            nums.append(float(p))
        except ValueError:
            continue

    if not nums:
        return None

    # Check if these look like raw ADC values (PIC 16F877A: 10-bit 0-1023)
    # All values are integers and at least one is > 100 and all are <= 1023
    all_int = all(n == int(n) for n in nums)
    looks_like_adc = all_int and any(n > 100 for n in nums) and all(0 <= n <= 1023 for n in nums)

    if looks_like_adc:
        return _parse_adc_values(nums)

    # Single value
    if len(nums) == 1:
        v = nums[0]
        if 0.5 <= v <= 5.0:
            return ParsedBattery(voltage_v=v, cell_voltages={"V1": v})
        elif v > 5.0:
            return ParsedBattery(voltage_v=v)
        return ParsedBattery(voltage_v=v)

    # Two values: voltage + current or two cell voltages
    if len(nums) == 2:
        if all(0.5 <= n <= 5.0 for n in nums):
            cells = {f"V{i+1}": v for i, v in enumerate(nums)}
            return ParsedBattery(voltage_v=sum(nums), cell_voltages=cells)
        return ParsedBattery(voltage_v=nums[0], current_a=nums[1])

    # If we have exactly 3 nums and they look like V,I,T (first > 5 = likely pack voltage)
    if len(nums) == 3 and nums[0] > 5.0:
        return ParsedBattery(voltage_v=nums[0], current_a=nums[1], temperature_c=nums[2])

    # If we have 4+ nums and first > 5 → V,I,T,SOC
    if len(nums) >= 4 and nums[0] > 5.0:
        return ParsedBattery(
            voltage_v=nums[0], current_a=nums[1], temperature_c=nums[2], soc_pct=nums[3]
        )

    # Otherwise treat all numbers as cell voltages (typical: 2.0–5.0 V range)
    cells = {f"V{i+1}": v for i, v in enumerate(nums)}
    total = sum(nums)
    return ParsedBattery(voltage_v=total, cell_voltages=cells)


def _parse_json(line: str) -> ParsedBattery | None:
    try:
        o = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(o, dict):
        return None

    cells: dict[str, float] = {}
    voltage = 0.0
    current = 0.0
    temp = 0.0
    soc: float | None = None

    for k, v in o.items():
        fv = _to_float(v)
        if fv is None:
            continue
        kl = k.lower().strip()

        # Cell voltages: V1, v2, cell1, cell_2, etc.
        m = re.match(r"(?:v|cell[_-]?)(\d+)", kl)
        if m:
            cells[f"V{m.group(1)}"] = fv
            continue

        if kl in ("voltage_v", "voltage", "volt", "v", "pack_v", "total_v"):
            voltage = fv
        elif kl in ("current_a", "current", "amp", "i", "a"):
            current = fv
        elif kl in ("temperature_c", "temperature", "temp", "t"):
            temp = fv
        elif kl in ("soc_pct", "soc", "charge"):
            soc = fv

    if not cells and voltage == 0.0:
        return None

    if cells and voltage == 0.0:
        voltage = sum(cells.values())

    return ParsedBattery(
        voltage_v=voltage, current_a=current, temperature_c=temp,
        soc_pct=soc, cell_voltages=cells or None,
    )


def _parse_kv(line: str) -> ParsedBattery | None:
    """Parse 'V1:3.65,V2:3.64,...,I:2.1,T:28.5,SOC:87' style lines."""
    # Split on comma or semicolon
    tokens = re.split(r"[,;]+", line)
    cells: dict[str, float] = {}
    voltage = 0.0
    current = 0.0
    temp = 0.0
    soc: float | None = None

    for tok in tokens:
        tok = tok.strip()
        m = re.match(r"([A-Za-z_]\w*)\s*[:=]\s*([-+]?\d*\.?\d+)", tok)
        if not m:
            continue
        key = m.group(1).strip()
        val = float(m.group(2))
        kl = key.lower()

        # Cell voltage keys
        cm = re.match(r"(?:v|cell[_-]?)(\d+)", kl)
        if cm:
            cells[f"V{cm.group(1)}"] = val
            continue

        if kl in ("v", "volt", "voltage", "pack", "total"):
            voltage = val
        elif kl in ("i", "a", "amp", "current"):
            current = val
        elif kl in ("t", "temp", "temperature"):
            temp = val
        elif kl in ("soc", "charge"):
            soc = val

    if not cells and voltage == 0.0:
        return None

    if cells and voltage == 0.0:
        voltage = sum(cells.values())

    return ParsedBattery(
        voltage_v=voltage, current_a=current, temperature_c=temp,
        soc_pct=soc, cell_voltages=cells or None,
    )


def _parse_adc_values(raw: list[float]) -> ParsedBattery:
    """
    Convert raw 10-bit ADC values (0-1023) to voltages.
    PIC 16F877A: Vref = 5.0V, 10-bit ADC → step = 5.0/1023.
    If a voltage divider is used (common for battery cells),
    the actual voltage = ADC_voltage * divider_ratio.

    With no divider info, we assume direct 0-5V measurement.
    Env var ADC_VREF (default 5.0) and ADC_DIVIDER (default 1.0) can override.
    """
    import os
    vref = float(os.environ.get("ADC_VREF", "5.0"))
    divider = float(os.environ.get("ADC_DIVIDER", "1.0"))
    adc_max = float(os.environ.get("ADC_BITS_MAX", "1023"))

    voltages = [round((v / adc_max) * vref * divider, 3) for v in raw]

    if len(voltages) == 1:
        return ParsedBattery(voltage_v=voltages[0], cell_voltages={"V1": voltages[0]})

    if len(voltages) == 2:
        return ParsedBattery(
            voltage_v=voltages[0], current_a=voltages[1],
            cell_voltages={"V1": voltages[0]},
        )

    if len(voltages) == 3:
        return ParsedBattery(
            voltage_v=voltages[0], current_a=voltages[1], temperature_c=voltages[2],
        )

    # 4+ values: treat as cell voltages
    cells = {f"V{i+1}": v for i, v in enumerate(voltages)}
    return ParsedBattery(
        voltage_v=sum(voltages), cell_voltages=cells,
    )


def _to_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
