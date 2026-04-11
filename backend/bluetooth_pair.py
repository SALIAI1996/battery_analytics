"""
Cross-platform Bluetooth pairing helper for HC-05 modules.

macOS:   Uses `blueutil` (brew install blueutil)
Windows: Uses built-in Windows Bluetooth APIs via subprocess
Linux:   Uses `bluetoothctl`

Flow:
  1. Normalise the MAC address
  2. Check if already paired
  3. If not, pair with PIN
  4. Connect
  5. Wait for the new serial port to appear
  6. Return the serial port path
"""

from __future__ import annotations

import glob
import json
import logging
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$")
_SYSTEM = platform.system()

# Shown when Linux has no bluetoothctl (Streamlit Cloud, Docker, most VPS — no BT adapter)
_MSG_LINUX_NO_BTCTL = (
    "Bluetooth pairing from this server is not available. "
    "Hosted apps (e.g. Streamlit Cloud) run in a data center with no Bluetooth radio and no access to your phone’s Bluetooth.\n\n"
    "What you can do:\n"
    "• Pair the HC-05 on your Android phone in Settings → Bluetooth (PIN 1234), then use a Bluetooth serial app on the phone to talk to the module, OR\n"
    "• Run this project on your Mac/PC (locally) where the OS can pair HC-05 and expose a serial port.\n\n"
    "From this browser you can still use **Simulated Battery** to try the dashboard."
)


def _normalise_mac(addr: str) -> str:
    addr = addr.strip().upper().replace("-", ":")
    if not _MAC_RE.match(addr):
        raise ValueError(f"Invalid MAC address: {addr!r}")
    return addr


def _run(cmd: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    log.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    combined = (result.stdout + result.stderr).strip()
    log.debug("  exit=%d out=%r", result.returncode, combined[:300])
    return result


@dataclass
class PairResult:
    mac: str
    already_paired: bool
    paired: bool
    connected: bool
    serial_port: str | None
    message: str


# ── macOS (blueutil) ────────────────────────────────────────────────────────

def _blueutil_path() -> Optional[str]:
    return shutil.which("blueutil")


def _macos_is_paired(mac: str) -> bool:
    bu = _blueutil_path()
    if not bu:
        return False
    try:
        r = _run([bu, "--is-paired", mac], timeout=10)
        return r.stdout.strip() == "1"
    except (subprocess.TimeoutExpired, OSError):
        return False


def _macos_is_connected(mac: str) -> bool:
    bu = _blueutil_path()
    if not bu:
        return False
    try:
        r = _run([bu, "--is-connected", mac], timeout=10)
        return r.stdout.strip() == "1"
    except (subprocess.TimeoutExpired, OSError):
        return False


def _macos_inquiry(duration: int = 8) -> list[dict]:
    bu = _blueutil_path()
    if not bu:
        return []
    try:
        r = _run([bu, "--inquiry", str(duration), "--format", "json"], timeout=duration + 15)
        return json.loads(r.stdout)
    except subprocess.TimeoutExpired:
        log.warning("Bluetooth inquiry timed out after %ds", duration + 15)
        return []
    except (json.JSONDecodeError, TypeError, OSError):
        return []


def _macos_serial_ports_snapshot() -> set[str]:
    return set(glob.glob("/dev/tty.*"))


def _macos_find_hc05_port(mac: str, ports_before: set[str] | None = None) -> str | None:
    mac_suffix = mac.replace(":", "")[-4:].upper()
    current = _macos_serial_ports_snapshot()

    if ports_before:
        new_ports = current - ports_before
        for p in sorted(new_ports):
            low = p.lower()
            if "incoming" in low or "debug" in low or "wlan" in low:
                continue
            return p

    for p in sorted(current):
        name = p.upper()
        if "HC-05" in name or "HC05" in name or "HC 05" in name:
            return p
        if mac_suffix in name:
            return p

    return None


def _macos_pair_and_connect(mac: str, pin: str = "1234") -> PairResult:
    bu = _blueutil_path()
    if not bu:
        return PairResult(
            mac=mac, already_paired=False, paired=False, connected=False,
            serial_port=None,
            message="blueutil not installed. Run: brew install blueutil",
        )

    already = _macos_is_paired(mac)
    ports_before = _macos_serial_ports_snapshot()

    if not already:
        log.info("Pairing with %s (PIN=%s) …", mac, pin)
        cmd = [bu, "--pair", mac]
        if pin:
            cmd.append(pin)
        try:
            r = _run(cmd, timeout=20)
            output = (r.stdout + r.stderr).strip()
        except subprocess.TimeoutExpired:
            port = _macos_find_hc05_port(mac)
            if port:
                return PairResult(
                    mac=mac, already_paired=False, paired=True, connected=False,
                    serial_port=port,
                    message=f"Pairing timed out but found port {port}. Try connecting to it.",
                )
            return PairResult(
                mac=mac, already_paired=False, paired=False, connected=False,
                serial_port=None,
                message=(
                    f"Pairing timed out. Make sure your HC-05 ({mac}) is:\n"
                    "1. Powered ON (LED blinking rapidly)\n"
                    "2. Within Bluetooth range (~10m)\n"
                    "3. Not already paired with another device\n"
                    "Try power cycling the HC-05 and retry."
                ),
            )

        if r.returncode != 0 and "already" not in output.lower():
            return PairResult(
                mac=mac, already_paired=False, paired=False, connected=False,
                serial_port=None,
                message=f"Pairing failed (exit {r.returncode}): {output}",
            )
        time.sleep(1)

    paired_now = _macos_is_paired(mac)
    existing_port = _macos_find_hc05_port(mac)

    if not paired_now and not existing_port:
        return PairResult(
            mac=mac, already_paired=already, paired=False, connected=False,
            serial_port=None,
            message=f"Device {mac} did not pair. Ensure HC-05 is powered on and in pairing mode.",
        )

    if not _macos_is_connected(mac):
        log.info("Connecting to %s …", mac)
        try:
            _run([bu, "--connect", mac], timeout=15)
        except subprocess.TimeoutExpired:
            log.warning("Connect timed out for %s", mac)
        time.sleep(2)

    serial_port = _macos_find_hc05_port(mac, ports_before)
    conn = _macos_is_connected(mac)

    return PairResult(
        mac=mac,
        already_paired=already,
        paired=True,
        connected=conn,
        serial_port=serial_port,
        message=(
            f"Paired and connected! Serial port: {serial_port}"
            if serial_port
            else (
                "Paired successfully"
                + (" and connected" if conn else "")
                + " but no serial port appeared yet.\n"
                "Try: Scan ports, or enter the port manually "
                "(e.g. /dev/tty.HC-05)."
            )
        ),
    )


# ── Windows ─────────────────────────────────────────────────────────────────

def _windows_find_hc05_port(mac: str) -> str | None:
    """Look for HC-05 COM ports in Windows registry / WMI."""
    try:
        import serial.tools.list_ports
        mac_suffix = mac.replace(":", "")[-4:].upper()
        for p in serial.tools.list_ports.comports():
            name = (p.description or "").upper()
            hwid = (p.hwid or "").upper()
            if "HC-05" in name or "HC05" in name or mac_suffix in hwid:
                return p.device
            if "BLUETOOTH" in name or "BTHENUM" in hwid:
                return p.device
    except Exception:
        pass
    return None


def _windows_pair_and_connect(mac: str, pin: str = "1234") -> PairResult:
    """
    On Windows, pairing is best done via system Settings.
    We check if the HC-05 COM port already exists.
    """
    serial_port = _windows_find_hc05_port(mac)

    try:
        ps_cmd = (
            f'Get-PnpDevice -FriendlyName "*{mac.replace(":", "")}*" '
            f'-ErrorAction SilentlyContinue | Select-Object Status,FriendlyName '
            f'| ConvertTo-Json'
        )
        r = _run(["powershell", "-Command", ps_cmd], timeout=10)
        device_info = r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        device_info = ""

    if serial_port:
        return PairResult(
            mac=mac, already_paired=True, paired=True, connected=True,
            serial_port=serial_port,
            message=f"HC-05 found on {serial_port}. Ready to stream!",
        )

    return PairResult(
        mac=mac, already_paired=False, paired=False, connected=False,
        serial_port=None,
        message=(
            f"HC-05 ({mac}) COM port not found.\n"
            "On Windows:\n"
            "1. Open Settings > Bluetooth & devices\n"
            "2. Click 'Add device' > Bluetooth\n"
            "3. Select HC-05 and enter PIN 1234\n"
            "4. After pairing, check Device Manager > Ports (COM & LPT)\n"
            "   for the HC-05 COM port number\n"
            "5. Enter the COM port (e.g. COM3) in the manual port field"
        ),
    )


# ── Linux ───────────────────────────────────────────────────────────────────

def _linux_pair_and_connect(mac: str, pin: str = "1234") -> PairResult:
    """Use bluetoothctl on Linux."""
    btctl = shutil.which("bluetoothctl")
    if not btctl:
        return PairResult(
            mac=mac, already_paired=False, paired=False, connected=False,
            serial_port=None,
            message=_MSG_LINUX_NO_BTCTL,
        )

    try:
        r = _run([btctl, "info", mac], timeout=10)
        already_paired = "Paired: yes" in r.stdout
    except (subprocess.TimeoutExpired, OSError):
        already_paired = False

    if not already_paired:
        try:
            _run([btctl, "pair", mac], timeout=20)
            _run([btctl, "trust", mac], timeout=10)
        except subprocess.TimeoutExpired:
            pass

    try:
        _run([btctl, "connect", mac], timeout=15)
    except subprocess.TimeoutExpired:
        pass

    rfcomm = shutil.which("rfcomm")
    serial_port = None
    if rfcomm:
        try:
            _run([rfcomm, "bind", "0", mac], timeout=10)
            serial_port = "/dev/rfcomm0"
        except (subprocess.TimeoutExpired, OSError):
            pass

    if not serial_port:
        for i in range(4):
            dev = f"/dev/rfcomm{i}"
            import os
            if os.path.exists(dev):
                serial_port = dev
                break

    return PairResult(
        mac=mac,
        already_paired=already_paired,
        paired=True,
        connected=serial_port is not None,
        serial_port=serial_port,
        message=(
            f"Connected! Serial port: {serial_port}"
            if serial_port
            else (
                f"Paired with {mac} but no rfcomm port bound.\n"
                f"Try: sudo rfcomm bind 0 {mac}\n"
                f"Then use /dev/rfcomm0 as the serial port."
            )
        ),
    )


# ── Public API ──────────────────────────────────────────────────────────────

def inquiry(duration: int = 8) -> list[dict]:
    """Discover nearby Bluetooth devices."""
    if _SYSTEM == "Darwin":
        return _macos_inquiry(duration)
    return []


def is_paired(mac: str) -> bool:
    if _SYSTEM == "Darwin":
        return _macos_is_paired(mac)
    return False


def is_connected(mac: str) -> bool:
    if _SYSTEM == "Darwin":
        return _macos_is_connected(mac)
    return False


def pair_and_connect(mac_raw: str, pin: str = "1234") -> PairResult:
    mac = _normalise_mac(mac_raw)

    if _SYSTEM == "Darwin":
        return _macos_pair_and_connect(mac, pin)
    elif _SYSTEM == "Windows":
        return _windows_pair_and_connect(mac, pin)
    elif _SYSTEM == "Linux":
        return _linux_pair_and_connect(mac, pin)
    else:
        return PairResult(
            mac=mac, already_paired=False, paired=False, connected=False,
            serial_port=None,
            message=f"Unsupported OS: {_SYSTEM}",
        )


def unpair(mac_raw: str) -> str:
    mac = _normalise_mac(mac_raw)
    if _SYSTEM == "Darwin":
        bu = _blueutil_path()
        if bu:
            _run([bu, "--unpair", mac])
    elif _SYSTEM == "Linux":
        btctl = shutil.which("bluetoothctl")
        if btctl:
            _run([btctl, "remove", mac])
    return f"Unpaired {mac}"
