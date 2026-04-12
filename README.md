## Environmental analytics — React + FastAPI + ThingSpeak

**Stack:** **Vite + React** (`frontend-react/`) for the browser UI, **FastAPI** (`backend/`) for the API, **ThingSpeak** for cloud sensor feeds.  
Optional: **USB serial** to a microcontroller for local battery telemetry (`POST /connect` with a COM/`/dev/tty.*` port).

Works on **macOS, Windows, and Linux**; production UI is typically **Vercel** + API on **Render** (see below).

### Deploy: GitHub → Render (API) + Vercel (React)

| Piece | Where | Notes |
|--------|--------|--------|
| **Code** | GitHub | Source of truth; push here for history and collaboration. |
| **Backend** | [Render](https://render.com) | Web service: `uvicorn backend.api:app --host 0.0.0.0 --port $PORT`. Use `render.yaml` (Blueprint) or create manually. Set `CORS_ORIGINS` to your Vercel URL(s), e.g. `https://your-app.vercel.app`. Optional: `THINGSPEAK_READ_API_KEY`. |
| **Frontend** | [Vercel](https://vercel.com) | **Root directory:** `frontend-react` (or repo root + root `vercel.json`). Framework: Vite. Set **`VITE_API_URL`** to your Render API base (no trailing slash), e.g. `https://environmental-analytics-api.onrender.com`. |

**If Vercel is wired only via CLI / SDK (no GitHub integration):** pushes to GitHub **do not** update the live site. You must **deploy again** after pulling `main`—for example `cd frontend-react && npm run deploy:prod`, or your automation that calls the [Vercel API](https://vercel.com/docs/rest-api) / [`@vercel/sdk`](https://vercel.com/docs/sdk) (e.g. create a deployment for the linked project). To get automatic deploys from `main`, connect the GitHub repo under **Project → Settings → Git** in Vercel (optional).

If Vercel keeps serving an **old UI** or builds look wrong: open **Project → Settings → General** and set **Root Directory** to **`frontend-react`**, save, then **Deployments → Redeploy** the latest commit on **`main`**. If you intentionally leave Root Directory empty (repo root), this repo now includes a **root `vercel.json`** that builds `frontend-react/` so the Vite app is what gets deployed.

After deploy, open the Vercel URL and use **Connect ThingSpeak** in the React UI.

**Local full-stack dev:** Terminal 1: `uvicorn backend.api:app --reload --port 8004`. Terminal 2: `cd frontend-react && npm install && npm run dev` — Vite proxies `/api/*` to `http://127.0.0.1:8004`, so leave `VITE_API_URL` unset. API docs: `http://127.0.0.1:8004/docs`.

### Environment variables

| File | Purpose |
|------|---------|
| **`.env.example`** (repo root) | Template for the **Python API**. Copy to **`.env`** in the repo root. Loaded automatically when `backend.api` starts. |
| **`frontend-react/.env.example`** | Template for the **React** app. Copy to **`frontend-react/.env`** or **`.env.local`**. Only variables prefixed with **`VITE_`** are exposed to the browser. |

**Backend (root `.env`):** `CORS_ORIGINS`, `THINGSPEAK_READ_API_KEY`, and optional `ADC_*` vars for UART parsing — see `.env.example`.

**Frontend (`frontend-react/.env`):** `VITE_API_URL` = your deployed API base URL (e.g. Render). Leave empty locally so Vite’s dev proxy is used.

### Deploy the frontend on Vercel (CLI)

1. **Backend first:** Deploy the FastAPI app on [Render](https://render.com) (or similar) and copy the public API URL (no trailing slash), e.g. `https://your-api.onrender.com`.

2. **Bearer token (API / SDK):** In Vercel: **Account Settings → Tokens** → create a token. Use it with the [Vercel REST API](https://vercel.com/docs/rest-api) or the [Vercel SDK](https://vercel.com/docs/sdk) (`@vercel/sdk`) as `bearerToken`. For normal CLI deploys you usually run **`vercel login`** instead (browser OAuth); the token is mainly for CI/CD and programmatic calls.

3. **CLI:** Deploy scripts use **`npx vercel@latest`** (no global install). Ensure dependencies are installed: `cd frontend-react && npm install`.

4. **Link and deploy (production):**

   ```bash
   cd frontend-react
   npx vercel link          # connect this folder to a Vercel project (first time)
   npx vercel env add VITE_API_URL production
   # paste your Render API URL when prompted, e.g. https://your-api.onrender.com
   npx vercel --prod        # or: npm run deploy:prod
   ```

5. **CORS:** On Render, set **`CORS_ORIGINS`** to your Vercel production URL (and preview URLs if you use PR previews), comma-separated.

#### Custom environments (e.g. staging)

Create a custom environment in the Vercel dashboard (**Project → Settings → Environments**) or via the API/SDK, then use the CLI:

```bash
# Deploy to a custom environment named "staging"
npx vercel deploy --target=staging

# Pull env vars from that environment into .env.local (optional)
npx vercel pull --environment=staging

# Add VITE_API_URL for staging (point at a staging API if you have one)
npx vercel env add VITE_API_URL staging
```

**SDK example** (optional — for automation only; keep tokens out of git):

```ts
import { Vercel } from "@vercel/sdk";

const vercel = new Vercel({ bearerToken: process.env.VERCEL_TOKEN! });

await vercel.environment.createCustomEnvironment({
  idOrName: "your-project-name-or-id",
  requestBody: {
    slug: "staging",
    description: "Staging — API on a separate Render service",
  },
});
```

Install the SDK with: `npm install @vercel/sdk` in a private tooling folder or CI job, not required for the app itself.

### How it works (ThingSpeak)

```
Sensors / MCU ──▶ ThingSpeak ── HTTPS JSON API ──▶ FastAPI poller
                                                          │
                                                 metrics ring buffer
                                                          │
                                                 React UI (Recharts)
```

### ThingSpeak setup

Default channel in the app is **3337776** (override with **Channel ID** in the UI or `THINGSPEAK_CHANNEL_ID` on the server).

1. Set **`THINGSPEAK_READ_API_KEY`** in the API server `.env` / Render (your **read** key from ThingSpeak). Do **not** commit keys to git.
2. In the React app, enter **Channel ID** (defaults to 3337776) and **Read API key** *or* rely on the server key only (leave key blank if the server has `THINGSPEAK_READ_API_KEY`).
3. Click **Connect ThingSpeak**. The backend loads history and polls the [Channel Feed API](https://www.mathworks.com/help/thingspeak/readdata.html).

**Default field mapping** (ThingSpeak fields 1–5):

| Field | Quantity        |
|------|-----------------|
| 1    | Temperature (°C) |
| 2    | Humidity (%)     |
| 3    | TDS              |
| 4    | pH               |
| 5    | Water quality (optional index) |

**Direct ThingSpeak URLs** (for reference — keys stay private):

- Feeds: `GET https://api.thingspeak.com/channels/<ID>/feeds.json?api_key=<READ_KEY>&results=2`
- Field 1: `GET https://api.thingspeak.com/channels/<ID>/fields/1.json?api_key=<READ_KEY>&results=2`
- Channel status: `GET https://api.thingspeak.com/channels/<ID>/status.json?api_key=<READ_KEY>`

**Proxied through this backend** (uses `THINGSPEAK_READ_API_KEY` + optional `THINGSPEAK_CHANNEL_ID` from the server — no key in the browser):

| Route | Maps to |
|--------|---------|
| `GET /thingspeak/channel-status` | `status.json` — channel name, etc. |
| `GET /thingspeak/feeds?results=100` | `feeds.json` |
| `GET /thingspeak/fields/1/data?results=100` | `fields/1.json` (use field `1`–`8`) |

Streaming metrics for the dashboard: `POST /connect-thingspeak` with JSON `channel_id`, `read_api_key` (optional if env key set), `poll_interval_sec`, `initial_results`.

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
