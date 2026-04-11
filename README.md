## Environmental analytics — React + FastAPI + ThingSpeak

**Stack:** **Vite + React** (`frontend-react/`) for the browser UI, **FastAPI** (`backend/`) for the API, **ThingSpeak** for cloud sensor feeds.  
Optional: **USB serial** to a microcontroller for local battery telemetry (`POST /connect` with a COM/`/dev/tty.*` port).

Works on **macOS, Windows, and Linux**; production UI is typically **Vercel** + API on **Render** (see below).

### Deploy: GitHub → Render (API) + Vercel (React)

| Piece | Where | Notes |
|--------|--------|--------|
| **Code** | GitHub | Push this repo; connect both hosts to the same repo. |
| **Backend** | [Render](https://render.com) | Web service: `uvicorn backend.api:app --host 0.0.0.0 --port $PORT`. Use `render.yaml` (Blueprint) or create manually. Set `CORS_ORIGINS` to your Vercel URL(s), e.g. `https://your-app.vercel.app`. Optional: `THINGSPEAK_READ_API_KEY`. |
| **Frontend** | [Vercel](https://vercel.com) | **Root directory:** `frontend-react`. Framework: Vite. Set **`VITE_API_URL`** to your Render API base (no trailing slash), e.g. `https://environmental-analytics-api.onrender.com`. |

After deploy, open the Vercel URL and use **Connect ThingSpeak** in the React UI.

**Local full-stack dev:** Terminal 1: `uvicorn backend.api:app --reload --port 8004`. Terminal 2: `cd frontend-react && npm install && npm run dev` — Vite proxies `/api/*` to `http://127.0.0.1:8004`, so leave `VITE_API_URL` unset. API docs: `http://127.0.0.1:8004/docs`.

### Environment variables

| File | Purpose |
|------|---------|
| **`.env.example`** (repo root) | Template for the **Python API**. Copy to **`.env`** in the repo root. Loaded automatically when `backend.api` starts. |
| **`frontend-react/.env.example`** | Template for the **React** app. Copy to **`frontend-react/.env`** or **`.env.local`**. Only variables prefixed with **`VITE_`** are exposed to the browser. |

**Backend (root `.env`):** `CORS_ORIGINS`, `THINGSPEAK_READ_API_KEY`, and optional `ADC_*` vars for UART parsing — see `.env.example`.

**Frontend (`frontend-react/.env`):** `VITE_API_URL` = your deployed API base URL (e.g. Render). Leave empty locally so Vite’s dev proxy is used.

### How it works (ThingSpeak)

```
Sensors / MCU ──▶ ThingSpeak ── HTTPS JSON API ──▶ FastAPI poller
                                                          │
                                                 metrics ring buffer
                                                          │
                                                 React UI (Recharts)
```

### ThingSpeak setup

1. In the React app, enter your **Channel ID** and **Read API key** (or set `THINGSPEAK_READ_API_KEY` on the server and leave the key blank in the UI).
2. Click **Connect ThingSpeak**. The backend loads recent history (`initial_results`) and polls the [Channel Feed API](https://www.mathworks.com/help/thingspeak/readdata.html) on a fixed interval.

**Default field mapping** (ThingSpeak fields 1–5):

| Field | Quantity        |
|------|-----------------|
| 1    | Temperature (°C) |
| 2    | Humidity (%)     |
| 3    | TDS              |
| 4    | pH               |
| 5    | Water quality (optional index) |

**API examples** (replace keys with your own):

- `GET https://api.thingspeak.com/channels/<ID>/feeds.json?api_key=<READ_KEY>&results=2`
- `GET https://api.thingspeak.com/channels/<ID>/fields/1.json?api_key=<READ_KEY>&results=2`

Backend route: `POST /connect-thingspeak` with JSON `channel_id`, `read_api_key`, `poll_interval_sec`, `initial_results`.

### What you get
- **ThingSpeak integration** — poll channel feeds; React charts and summary insights
- **REST API** — OpenAPI at `/docs` (ThingSpeak connect, optional serial, simulation, metrics)
- **Serial streaming** — `POST /connect` with a port path; `GET /metrics/latest` for telemetry
- **Per-cell / pack metrics** — in API responses when using serial or simulation
- **Serial test** — `GET /serial-test` to debug raw bytes
- **Simulation mode** — `POST /connect` with simulated device id for testing without hardware

### Quickstart

```bash
cd /Users/bajiraosali/Desktop/Battery_analytics
python -m venv .venv
source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\activate           # Windows
pip install -r requirements.txt
cd frontend-react && npm install && cd ..
```

### Start the app

**Terminal 1 — Backend:**
```bash
uvicorn backend.api:app --reload --reload-dir backend --port 8004
```

**Terminal 2 — Frontend:**
```bash
cd frontend-react && npm run dev
```
Then open the printed URL (usually `http://127.0.0.1:5173`).

### In the React app

**ThingSpeak (recommended for hosted / cloud):**
1. Enter **Channel ID** and **Read API key** (or rely on `THINGSPEAK_READ_API_KEY` on the API).
2. Adjust poll interval and how many past points to load.
3. Click **Connect ThingSpeak** and watch the charts update.

**Optional serial (battery pack):** use **FastAPI** at `http://127.0.0.1:8004/docs` — e.g. `GET /devices`, `POST /connect`, `GET /metrics/latest`. The React UI focuses on ThingSpeak; use curl/Postman or extend the UI for serial workflows.

**Troubleshooting no serial data:**
1. `GET /serial-test?port=...` to see if raw bytes arrive
2. If no data, your MCU isn't sending — check wiring and firmware

### Data format from your MCU (optional serial path)

Send **one ASCII line per sample** over UART (USB–serial adapter), ending with `\n`. Supported formats:

**CSV (simplest):**
```
3.65,3.64,3.66,3.63
```
→ Interpreted as cell voltages V1–V4. Pack voltage = sum.

**Key:value pairs:**
```
V1:3.65,V2:3.64,V3:3.66,V4:3.63,I:2.1,T:28.5,SOC:87
```

**JSON:**
```json
{"V1":3.65,"V2":3.64,"V3":3.66,"V4":3.63,"current":2.1,"temp":28.5,"soc":87}
```

**Simple 3-value (pack only):**
```
52.6,2.1,28.5
```
→ Interpreted as pack voltage, current, temperature.

Raw ADC integers (0–1023) are converted using:
`voltage = (ADC / 1023) * Vref * divider_ratio`

To calibrate, set environment variables before starting the backend:
```bash
export ADC_VREF=5.0      # PIC reference voltage (default 5.0V)
export ADC_DIVIDER=3.0    # Voltage divider ratio (e.g., 3:1 for 15V battery)
```

### Arduino example

```cpp
void loop() {
  float v1 = readCell(1);
  float v2 = readCell(2);
  float v3 = readCell(3);
  float v4 = readCell(4);
  float current = readCurrent();
  float temp = readTemp();

  Serial.print("V1:"); Serial.print(v1, 3);
  Serial.print(",V2:"); Serial.print(v2, 3);
  Serial.print(",V3:"); Serial.print(v3, 3);
  Serial.print(",V4:"); Serial.print(v4, 3);
  Serial.print(",I:"); Serial.print(current, 2);
  Serial.print(",T:"); Serial.println(temp, 1);

  delay(200);
}
```

### Troubleshooting (serial)

| Problem | Fix |
|---------|-----|
| "Permission denied" on port | Linux: add your user to `dialout` or fix device permissions |
| Port opens but no data | MCU not sending; check wiring (MCU TX → adapter RX, GND common) and baud rate |
| Data shows but all zeros | Baud rate mismatch — try 9600, 38400, or 115200 |
| Port busy | Another app has the port open (close Arduino IDE serial monitor, etc.) |
| Windows: COM port not found | Check Device Manager → Ports (COM & LPT) for your USB adapter |
