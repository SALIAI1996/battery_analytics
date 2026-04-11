from __future__ import annotations

import os
import pathlib
import sys
from datetime import datetime, timezone
from typing import Any

# Repo root (for `backend.*` imports when running `streamlit run frontend/app.py`)
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Battery Analytics — HC-05", page_icon="🔋", layout="wide")


@st.cache_resource
def _start_embedded_fastapi() -> str:
    """
    Streamlit Community Cloud runs only this process — no separate uvicorn.
    Start FastAPI in a background thread so the UI can reach /status, /connect, etc.
    """
    import socket
    import threading
    import time

    import uvicorn

    from backend.api import app as fastapi_app

    port = int(os.environ.get("FASTAPI_EMBED_PORT", os.environ.get("BACKEND_PORT", "8004")))
    host = "127.0.0.1"

    def _serve() -> None:
        cfg = uvicorn.Config(
            fastapi_app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        uvicorn.Server(cfg).run()

    threading.Thread(target=_serve, daemon=True, name="battery-analytics-api").start()

    deadline = time.time() + 20.0
    while time.time() < deadline:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.25)
            sock.connect((host, port))
            sock.close()
            return f"http://{host}:{port}"
        except OSError:
            time.sleep(0.12)
    return f"http://{host}:{port}"


def _ensure_backend_url() -> None:
    """Use BACKEND_URL from secrets/env if set; otherwise embed FastAPI (Cloud-friendly)."""
    if os.environ.get("BACKEND_URL", "").strip():
        return
    if os.environ.get("NO_EMBED_FASTAPI", "").lower() in ("1", "true", "yes"):
        p = os.environ.get("BACKEND_PORT", "8004")
        os.environ["BACKEND_URL"] = f"http://127.0.0.1:{p}"
        return
    os.environ["BACKEND_URL"] = _start_embedded_fastapi()


_ensure_backend_url()


def backend_base_url() -> str:
    return os.environ.get("BACKEND_URL", "http://127.0.0.1:8004").rstrip("/")


def api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    r = requests.get(f"{backend_base_url()}{path}", params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def api_post(path: str, json: dict[str, Any] | None = None) -> Any:
    r = requests.post(f"{backend_base_url()}{path}", json=json, timeout=15)
    r.raise_for_status()
    return r.json()

for key, default in [
    ("device_list", []),
    ("selected_idx", 0),
    ("points", []),
    ("last_ts", None),
    ("cap", 4000),
    ("pair_result", None),
    ("bt_scan", []),
    ("term_since_id", 0),
    ("term_display", ""),
]:
    st.session_state.setdefault(key, default)

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("HC-05 Connection")
    st.caption(f"Backend → `{backend_base_url()}`")

    with st.expander("Setup guide", expanded=False):
        st.markdown(
            "**Option A — USB serial cable (recommended on Mac):**\n"
            "1. Wire MCU TX/RX to a USB-TTL adapter (CH340/CP2102/FTDI)\n"
            "2. Plug USB into Mac → port appears as `/dev/tty.usbserial-*`\n"
            "3. Scan → pick port → Connect\n\n"
            "**Option B — HC-05 Bluetooth:**\n"
            "1. Pair in *System Settings → Bluetooth* (PIN `1234`)\n"
            "2. Port appears as `/dev/tty.HC-05*` or `/dev/tty.HC05*`\n"
            "3. If no port appears, use the manual entry below\n\n"
            "**macOS note:** Classic BT (HC-05) is unreliable on macOS M1+. "
            "USB serial is strongly recommended."
        )

    st.divider()
    st.subheader("Bluetooth Pairing")

    with st.expander("Using Android / iPhone or Streamlit Cloud?", expanded=False):
        st.markdown(
            "Pairing and serial ports run on the **computer that hosts this app**, not on your "
            "phone. **Streamlit Cloud** has **no Bluetooth** (you may see a message about that) — "
            "use **Simulated Battery** to demo the UI, or install and run the app on your **Mac/PC** "
            "where you can pair the HC-05 and see a real serial port."
        )

    if st.button("📡 Scan Nearby Bluetooth", use_container_width=True):
        with st.spinner("Scanning for Bluetooth devices (~8 sec)…"):
            try:
                bt_devices = api_get("/bluetooth-scan", params={"duration": 8})
                if bt_devices:
                    st.session_state["bt_scan"] = bt_devices
                    st.success(f"Found {len(bt_devices)} device(s)")
                else:
                    st.session_state["bt_scan"] = []
                    st.warning("No Bluetooth devices found nearby. Make sure your HC-05 is powered on.")
            except Exception as exc:
                st.error(f"Bluetooth scan failed: {exc}")

    bt_scan: list[dict] = st.session_state.get("bt_scan", [])
    if bt_scan:
        with st.expander(f"Nearby devices ({len(bt_scan)})", expanded=True):
            for dev in bt_scan:
                addr = dev.get("address", "").replace("-", ":")
                name = dev.get("name", "Unknown")
                st.code(f"{addr}  —  {name}", language=None)

    mac_address = st.text_input(
        "HC-05 MAC address",
        placeholder="00:23:09:01:5A:78",
        help="Enter the Bluetooth MAC address printed on your HC-05 module.",
    )
    bt_pin = st.text_input("PIN", value="1234", help="Default HC-05 PIN is 1234.")

    pair_col1, pair_col2 = st.columns(2)
    with pair_col1:
        pair_clicked = st.button(
            "🔗 Pair & Connect", use_container_width=True, disabled=not mac_address.strip()
        )
    with pair_col2:
        pair_only_clicked = st.button(
            "🔗 Pair Only", use_container_width=True, disabled=not mac_address.strip()
        )

    if pair_clicked and mac_address.strip():
        with st.spinner(f"Pairing with {mac_address.strip()} …"):
            try:
                result = api_post(
                    "/pair-bluetooth",
                    json={"mac_address": mac_address.strip(), "pin": bt_pin},
                )
                st.session_state["pair_result"] = result
                if result.get("paired") and result.get("serial_port"):
                    st.success(f"Paired! Port: `{result['serial_port']}`")
                    with st.spinner(f"Connecting to {result['serial_port']} …"):
                        resp = api_post(
                            "/connect",
                            json={
                                "device_id": result["serial_port"],
                                "simulated": False,
                                "baudrate": 9600,
                            },
                        )
                        st.session_state["points"] = []
                        st.session_state["last_ts"] = None
                        st.session_state["term_since_id"] = 0
                        st.session_state["term_display"] = ""
                        st.success(resp.get("message", "Connected!"))
                elif result.get("paired"):
                    st.warning(result.get("message", "Paired but no serial port found."))
                else:
                    st.error(result.get("message", "Pairing failed."))
            except Exception as exc:
                st.error(f"Pair failed: {exc}")

    if pair_only_clicked and mac_address.strip():
        with st.spinner(f"Pairing with {mac_address.strip()} …"):
            try:
                result = api_post(
                    "/pair-bluetooth",
                    json={"mac_address": mac_address.strip(), "pin": bt_pin},
                )
                st.session_state["pair_result"] = result
                if result.get("paired"):
                    port_msg = f" Port: `{result['serial_port']}`" if result.get("serial_port") else ""
                    st.success(f"Paired successfully!{port_msg}")
                else:
                    st.error(result.get("message", "Pairing failed."))
            except Exception as exc:
                st.error(f"Pair failed: {exc}")

    pair_result = st.session_state.get("pair_result")
    if pair_result:
        with st.expander("Last pairing result", expanded=False):
            st.json(pair_result)

    st.divider()
    st.subheader("Manual Connection")

    if st.button("🔍 Scan ports", use_container_width=True):
        with st.spinner("Listing serial ports…"):
            try:
                st.session_state["device_list"] = api_get("/devices", params={"include_sim": True})
                st.session_state["selected_idx"] = 0
            except Exception as exc:
                st.error(f"Scan failed — is the backend running?\n\n`{exc}`")

    devices: list[dict] = st.session_state["device_list"]

    if devices:
        labels = [
            f'{"🟢 SIM: " if d.get("is_simulated") else "🔵 "}'
            f'{d.get("name") or d.get("device_id") or "Unknown"}'
            for d in devices
        ]
        idx = st.selectbox("Available ports", range(len(devices)), format_func=lambda i: labels[i])
        st.session_state["selected_idx"] = idx
        chosen = devices[idx]
    else:
        st.info("Press **Scan ports** to find serial ports or simulation.")
        chosen = None

    manual_port = st.text_input(
        "Or enter port manually",
        placeholder="/dev/tty.HC-05-DevB",
        help="Type a serial port path if your HC-05 doesn't show in the scan list.",
    )
    if manual_port and manual_port.strip():
        chosen = {"device_id": manual_port.strip(), "name": manual_port.strip(), "is_simulated": False}

    baudrate = st.selectbox("Baud rate", [9600, 19200, 38400, 57600, 115200], index=0)

    col_c, col_d = st.columns(2)
    with col_c:
        connect_clicked = st.button(
            "⚡ Connect", type="primary", use_container_width=True, disabled=chosen is None
        )
    with col_d:
        disconnect_clicked = st.button("🔌 Disconnect", use_container_width=True)

    if connect_clicked and chosen is not None:
        with st.spinner(f'Connecting to {chosen.get("name", chosen["device_id"])}…'):
            try:
                resp = api_post(
                    "/connect",
                    json={
                        "device_id": chosen["device_id"],
                        "simulated": bool(chosen.get("is_simulated")),
                        "baudrate": baudrate,
                    },
                )
                st.session_state["points"] = []
                st.session_state["last_ts"] = None
                st.session_state["term_since_id"] = 0
                st.session_state["term_display"] = ""
                st.success(resp.get("message", "Connected."))
            except Exception as exc:
                st.error(f"Connect failed: {exc}")

    if disconnect_clicked:
        try:
            api_post("/disconnect")
            st.session_state["points"] = []
            st.session_state["last_ts"] = None
            st.session_state["term_since_id"] = 0
            st.session_state["term_display"] = ""
            st.info("Disconnected.")
        except Exception as exc:
            st.error(f"Disconnect failed: {exc}")

    if chosen and not chosen.get("is_simulated"):
        if st.button("🧪 Test Serial Port", use_container_width=True):
            port = chosen["device_id"]
            with st.spinner(f"Listening on {port} for 5s…"):
                try:
                    result = api_get("/serial-test", params={"port": port, "baudrate": baudrate, "duration": 5})
                    if result.get("raw_bytes", 0) > 0:
                        st.success(result["message"])
                        with st.expander("Raw lines received", expanded=True):
                            for line in result.get("lines", []):
                                st.code(line, language=None)
                    else:
                        st.warning(result["message"])
                        st.info(
                            "**No data from HC-05.** Check:\n"
                            "1. Is your MCU (Arduino/ESP32) connected to HC-05 TX pin?\n"
                            "2. Is the MCU firmware running and sending serial data?\n"
                            "3. Does the baud rate match between MCU and this app?\n"
                            "4. Is the HC-05 LED solid (connected) or blinking (not connected)?"
                        )
                except Exception as exc:
                    st.error(f"Test failed: {exc}")

    st.divider()
    st.subheader("Live settings")
    refresh_ms = st.slider("Refresh interval (ms)", 200, 2000, 500, 100)
    st.session_state["cap"] = st.slider("Max points kept", 500, 10_000, 4000, 500)

# ── Main area ────────────────────────────────────────────────────────────────

st.title("Battery Analytics — HC-05")

try:
    status = api_get("/status")
except Exception as exc:
    st.error(
        f"Backend not reachable at `{backend_base_url()}`.\n\n"
        "**Local dev:** run `uvicorn backend.api:app --port 8004` in another terminal, or unset "
        "`NO_EMBED_FASTAPI` so this app starts the API automatically.\n\n"
        f"`{exc}`"
    )
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Mode", status.get("mode", "none"))
c2.metric("Connected", "Yes" if status.get("connected") else "No")
c3.metric("Streaming", "Yes" if status.get("streaming") else "No")
c4.metric("Device", status.get("active_device_id") or "—")

st.subheader("Bluetooth Serial Monitor")
st.caption(
    "Live **RX** (from your PIC/Arduino via HC-05) and **TX** (to the device), similar to "
    "**Arduino Bluetooth Controller** on Android."
)

if status.get("mode") == "serial" and status.get("active_device_id"):
    if status.get("connected") or status.get("streaming"):
        try:
            tr = api_get(
                "/terminal/log",
                params={"since_id": st.session_state["term_since_id"], "limit": 500},
            )
            if tr.get("ok") and tr.get("lines"):
                for line in tr["lines"]:
                    arrow = "← RX" if line.get("dir") == "rx" else "→ TX"
                    st.session_state["term_display"] += f"{arrow}  {line.get('text', '')}\n"
                st.session_state["term_since_id"] = int(tr.get("last_id", st.session_state["term_since_id"]))
        except Exception as exc:
            st.caption(f"Terminal log: {exc}")
        td = st.session_state["term_display"]
        if len(td) > 300_000:
            st.session_state["term_display"] = td[-250_000:]

    tx_col1, tx_col2, tx_col3, tx_col4 = st.columns([3, 1, 1, 1])
    with tx_col1:
        tx_text = st.text_input("Send to device", key="bt_tx_input", placeholder="AT, commands, or text…")
    with tx_col2:
        tx_crlf = st.checkbox("Append CR+LF", value=True, key="bt_tx_crlf")
    with tx_col3:
        send_tx = st.button("Send", use_container_width=True, type="secondary")
    with tx_col4:
        clear_tx = st.button("Clear log", use_container_width=True)

    if send_tx:
        try:
            api_post(
                "/terminal/send",
                json={"text": tx_text or "", "append_crlf": bool(tx_crlf)},
            )
        except Exception as exc:
            st.error(f"Send failed: {exc}")
    if clear_tx:
        try:
            api_post("/terminal/clear")
            st.session_state["term_since_id"] = 0
            st.session_state["term_display"] = ""
        except Exception as exc:
            st.error(f"Clear failed: {exc}")

    st.code(
        st.session_state.get("term_display") or "— Waiting for serial data… Connect PIC TX → HC-05 RX. —",
        language="text",
    )
else:
    st.info(
        "Connect to an **HC-05 / serial port** in the sidebar to see a live stream here "
        "(same idea as the Arduino Bluetooth Controller app)."
    )

st.subheader("Live telemetry")

st_autorefresh(interval=refresh_ms, key="tick")

if status.get("streaming") and status.get("active_device_id"):
    try:
        resp = api_get("/metrics/latest", params={"since": st.session_state["last_ts"], "limit": 1000})
        new_pts = resp.get("points", [])
        if new_pts:
            pts = st.session_state["points"]
            pts.extend(new_pts)
            cap = st.session_state["cap"]
            st.session_state["points"] = pts[-cap:] if len(pts) > cap else pts
            st.session_state["last_ts"] = new_pts[-1]["ts"]
    except Exception as exc:
        st.warning(f"Fetch error (will retry): {exc}")

points: list[dict] = st.session_state["points"]

if not points:
    if status.get("streaming") and status.get("mode") == "serial":
        st.warning(
            "**Serial port is open but no data received yet.**\n\n"
            "Your HC-05 is connected, but your MCU needs to send data over UART. "
            "Make sure your Arduino/ESP32 is:\n"
            "- Connected to HC-05 (TX→RX, RX→TX, GND→GND)\n"
            "- Running firmware that sends serial data (e.g. `Serial.println(\"3.65,3.64,3.66,3.63,2.1,28.5\")`)\n"
            "- Using the same baud rate as selected in the sidebar\n\n"
            "Use the **Test Serial Port** button in the sidebar to check for incoming data."
        )
    else:
        st.info("No data yet — connect to a device to start streaming.")
else:
    last = points[-1]

    # ── Summary metrics ──────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Pack Voltage (V)", f'{last["voltage_v"]:.2f}')
    m2.metric("Current (A)", f'{last["current_a"]:.2f}')
    m3.metric("Temp (°C)", f'{last["temperature_c"]:.2f}')
    soc = last.get("soc_pct")
    m4.metric("SOC (%)", f"{soc:.1f}" if soc is not None else "—")

    # ── Per-cell voltages (V1, V2, V3, V4…) ─────────────────────────────
    cells = last.get("cell_voltages")
    if cells:
        st.subheader("Cell voltages")
        cell_keys = sorted(cells.keys(), key=lambda k: int(k[1:]) if k[1:].isdigit() else 0)
        cols = st.columns(len(cell_keys))
        for col, ck in zip(cols, cell_keys):
            col.metric(ck, f"{cells[ck]:.3f} V")

        # Per-cell chart over time
        fig_cells = go.Figure()
        all_cell_keys: set[str] = set()
        for p in points:
            cv = p.get("cell_voltages")
            if cv:
                all_cell_keys.update(cv.keys())
        for ck in sorted(all_cell_keys, key=lambda k: int(k[1:]) if k[1:].isdigit() else 0):
            ts_c = []
            vs_c = []
            for p in points:
                cv = p.get("cell_voltages")
                if cv and ck in cv:
                    ts_c.append(p["ts"])
                    vs_c.append(cv[ck])
            fig_cells.add_trace(go.Scatter(x=ts_c, y=vs_c, mode="lines", name=ck))

        fig_cells.update_layout(
            title="Cell Voltages Over Time",
            height=400,
            margin=dict(l=20, r=20, t=40, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            xaxis=dict(title="Time"),
            yaxis=dict(title="Cell Voltage (V)"),
        )
        st.plotly_chart(fig_cells, use_container_width=True)

    # ── Pack voltage / current / temp chart ──────────────────────────────
    st.subheader("Pack overview")
    ts = [p["ts"] for p in points]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ts, y=[p["voltage_v"] for p in points], mode="lines", name="Pack Voltage (V)"))
    fig.add_trace(go.Scatter(
        x=ts, y=[p["current_a"] for p in points], mode="lines", name="Current (A)", yaxis="y2"
    ))
    fig.add_trace(go.Scatter(
        x=ts, y=[p["temperature_c"] for p in points], mode="lines", name="Temp (°C)", yaxis="y3"
    ))
    socs = [p.get("soc_pct") for p in points]
    if any(s is not None for s in socs):
        fig.add_trace(go.Scatter(x=ts, y=socs, mode="lines", name="SOC (%)", yaxis="y4"))

    fig.update_layout(
        height=450,
        margin=dict(l=20, r=20, t=30, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(title="Time", showgrid=True),
        yaxis=dict(title="Voltage (V)", side="left"),
        yaxis2=dict(title="Current (A)", overlaying="y", side="right", showgrid=False),
        yaxis3=dict(title="Temp (°C)", overlaying="y", side="right", position=0.95, showgrid=False),
        yaxis4=dict(title="SOC (%)", overlaying="y", side="right", position=0.90, showgrid=False),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Raw debug line ───────────────────────────────────────────────────
    if last.get("raw_line"):
        with st.expander("Last raw UART line"):
            st.code(last["raw_line"])

st.caption(f"Tick: {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")
