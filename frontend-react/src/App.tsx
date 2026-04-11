import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiBase, apiGet, apiPost } from "./api";
import type { BatteryMetric, LatestResponse, StatusResponse } from "./types";
import "./App.css";

const MAX_POINTS = 4000;

function fmt(v: number | null | undefined, nd = 2): string {
  if (v === null || v === undefined) return "—";
  if (Number.isNaN(v)) return "—";
  return v.toFixed(nd);
}

function anySeries(points: BatteryMetric[], key: keyof BatteryMetric): boolean {
  return points.some((p) => p[key] !== null && p[key] !== undefined);
}

export default function App() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [points, setPoints] = useState<BatteryMetric[]>([]);
  const [lastTs, setLastTs] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [channelId, setChannelId] = useState(3269475);
  const [readKey, setReadKey] = useState("");
  const [pollSec, setPollSec] = useState(15);
  const [initialN, setInitialN] = useState(500);

  const baseConfigured = useMemo(() => {
    const b = apiBase();
    return Boolean(b) || import.meta.env.DEV;
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await apiGet<StatusResponse>("/status");
      setStatus(s);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const pullLatest = useCallback(async () => {
    if (!status?.active_device_id || !status.streaming) return;
    try {
      const resp = await apiGet<LatestResponse>("/metrics/latest", {
        since: lastTs ?? undefined,
        limit: 1000,
      });
      const newPts = resp.points ?? [];
      if (newPts.length) {
        setPoints((prev) => {
          const merged = [...prev, ...newPts];
          return merged.length > MAX_POINTS ? merged.slice(-MAX_POINTS) : merged;
        });
        setLastTs(newPts[newPts.length - 1]!.ts);
      }
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [status?.active_device_id, status?.streaming, lastTs]);

  useEffect(() => {
    refreshStatus();
    const id = window.setInterval(refreshStatus, 5000);
    return () => window.clearInterval(id);
  }, [refreshStatus]);

  useEffect(() => {
    const id = window.setInterval(pullLatest, 1500);
    return () => window.clearInterval(id);
  }, [pullLatest]);

  const connectThingSpeak = async () => {
    setLoading(true);
    setErr(null);
    try {
      await apiPost("/connect-thingspeak", {
        channel_id: channelId,
        read_api_key: readKey.trim(),
        poll_interval_sec: pollSec,
        initial_results: initialN,
      });
      setPoints([]);
      setLastTs(null);
      await refreshStatus();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const disconnect = async () => {
    setLoading(true);
    setErr(null);
    try {
      await apiPost("/disconnect", {});
      setPoints([]);
      setLastTs(null);
      await refreshStatus();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const last = points.length ? points[points.length - 1] : null;
  const isTs = last?.source === "thingspeak";

  const chartData = useMemo(() => {
    return points.map((p) => ({
      t: p.ts,
      time: new Date(p.ts).toLocaleTimeString(),
      temperature_c: p.temperature_c,
      humidity_pct: p.humidity_pct ?? undefined,
      tds_ppm: p.tds_ppm ?? undefined,
      ph: p.ph ?? undefined,
      water_quality_index: p.water_quality_index ?? undefined,
    }));
  }, [points]);

  const insights = useMemo(() => {
    if (!isTs || !points.length) return null;
    const temps = points.map((p) => p.temperature_c).filter((x) => x != null) as number[];
    const phs = points.map((p) => p.ph).filter((x) => x != null) as number[];
    const tds = points.map((p) => p.tds_ppm).filter((x) => x != null) as number[];
    const lines: string[] = [];
    if (temps.length) {
      lines.push(
        `Temperature min / max: ${Math.min(...temps).toFixed(2)} / ${Math.max(...temps).toFixed(2)} °C`
      );
    }
    if (phs.length) {
      lines.push(`pH min / max: ${Math.min(...phs).toFixed(2)} / ${Math.max(...phs).toFixed(2)}`);
    }
    if (tds.length) {
      lines.push(`TDS min / max: ${Math.min(...tds).toFixed(0)} / ${Math.max(...tds).toFixed(0)} ppm`);
    }
    return lines.length ? lines : null;
  }, [isTs, points]);

  return (
    <div className="app">
      <header className="header">
        <h1>Environmental analytics</h1>
        <p>
          React UI for ThingSpeak-backed telemetry. Backend runs on Render; configure{" "}
          <code className="mono">VITE_API_URL</code> on Vercel.
        </p>
      </header>

      <div className="layout">
        <aside className="panel">
          <h2>ThingSpeak</h2>
          {!baseConfigured && (
            <div className="banner warn">
              Set <span className="mono">VITE_API_URL</span> to your Render API URL before deploy. For local dev,
              run <span className="mono">vite</span> and <span className="mono">uvicorn</span> (proxy uses{" "}
              <span className="mono">/api</span>).
            </div>
          )}
          <div className="field">
            <label htmlFor="ch">Channel ID</label>
            <input
              id="ch"
              type="number"
              min={1}
              value={channelId}
              onChange={(e) => setChannelId(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="key">Read API key</label>
            <input
              id="key"
              type="password"
              autoComplete="off"
              placeholder="Or use THINGSPEAK_READ_API_KEY on the server"
              value={readKey}
              onChange={(e) => setReadKey(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="poll">Backend poll interval (sec)</label>
            <input
              id="poll"
              type="number"
              min={5}
              max={3600}
              value={pollSec}
              onChange={(e) => setPollSec(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="init">Initial history points</label>
            <input
              id="init"
              type="number"
              min={50}
              max={8000}
              step={50}
              value={initialN}
              onChange={(e) => setInitialN(Number(e.target.value))}
            />
          </div>
          <div className="row">
            <button type="button" className="btn btn-primary" disabled={loading} onClick={connectThingSpeak}>
              Connect ThingSpeak
            </button>
            <button type="button" className="btn" disabled={loading} onClick={disconnect}>
              Disconnect
            </button>
          </div>
          {err && <p className="error">{err}</p>}
        </aside>

        <main className="main">
          <div className="status-bar">
            <span>
              Mode: <strong>{status?.mode ?? "—"}</strong>
            </span>
            <span>
              Connected: <strong>{status?.connected ? "Yes" : "No"}</strong>
            </span>
            <span>
              Streaming: <strong>{status?.streaming ? "Yes" : "No"}</strong>
            </span>
            <span>
              Device: <strong className="mono">{status?.active_device_id ?? "—"}</strong>
            </span>
          </div>

          {!points.length && status?.mode === "thingspeak" && status.streaming && (
            <div className="banner">Waiting for first samples from ThingSpeak…</div>
          )}

          {last && isTs && (
            <>
              <div className="metrics">
                <div className="metric">
                  <div className="label">Temperature (°C)</div>
                  <div className="value">{fmt(last.temperature_c)}</div>
                </div>
                <div className="metric">
                  <div className="label">Humidity (%)</div>
                  <div className="value">{fmt(last.humidity_pct ?? undefined)}</div>
                </div>
                <div className="metric">
                  <div className="label">TDS</div>
                  <div className="value">{fmt(last.tds_ppm ?? undefined, 1)}</div>
                </div>
                <div className="metric">
                  <div className="label">pH</div>
                  <div className="value">{fmt(last.ph ?? undefined)}</div>
                </div>
                <div className="metric">
                  <div className="label">Water quality</div>
                  <div className="value">{fmt(last.water_quality_index ?? undefined)}</div>
                </div>
              </div>

              {(anySeries(points, "temperature_c") || anySeries(points, "humidity_pct")) && (
                <div className="chart-wrap">
                  <h3>Temperature & humidity</h3>
                  <ResponsiveContainer width="100%" height={320}>
                    <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#243044" />
                      <XAxis dataKey="time" tick={{ fill: "#8b9cb3", fontSize: 11 }} />
                      <YAxis yAxisId="l" tick={{ fill: "#8b9cb3", fontSize: 11 }} />
                      <YAxis yAxisId="r" orientation="right" tick={{ fill: "#8b9cb3", fontSize: 11 }} />
                      <Tooltip
                        contentStyle={{ background: "#141a22", border: "1px solid #243044" }}
                        labelStyle={{ color: "#e8edf5" }}
                      />
                      <Legend />
                      {anySeries(points, "temperature_c") && (
                        <Line
                          yAxisId="l"
                          type="monotone"
                          dataKey="temperature_c"
                          name="Temp °C"
                          stroke="#3d9cf0"
                          dot={false}
                          strokeWidth={2}
                        />
                      )}
                      {anySeries(points, "humidity_pct") && (
                        <Line
                          yAxisId="r"
                          type="monotone"
                          dataKey="humidity_pct"
                          name="Humidity %"
                          stroke="#34d399"
                          dot={false}
                          strokeWidth={2}
                        />
                      )}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              {(anySeries(points, "tds_ppm") || anySeries(points, "ph") || anySeries(points, "water_quality_index")) && (
                <div className="chart-wrap">
                  <h3>TDS, pH & water quality</h3>
                  <ResponsiveContainer width="100%" height={320}>
                    <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#243044" />
                      <XAxis dataKey="time" tick={{ fill: "#8b9cb3", fontSize: 11 }} />
                      <YAxis yAxisId="a" tick={{ fill: "#8b9cb3", fontSize: 11 }} />
                      <YAxis yAxisId="b" orientation="right" tick={{ fill: "#8b9cb3", fontSize: 11 }} />
                      <Tooltip
                        contentStyle={{ background: "#141a22", border: "1px solid #243044" }}
                        labelStyle={{ color: "#e8edf5" }}
                      />
                      <Legend />
                      {anySeries(points, "tds_ppm") && (
                        <Line
                          yAxisId="a"
                          type="monotone"
                          dataKey="tds_ppm"
                          name="TDS"
                          stroke="#fbbf24"
                          dot={false}
                          strokeWidth={2}
                        />
                      )}
                      {anySeries(points, "ph") && (
                        <Line
                          yAxisId="b"
                          type="monotone"
                          dataKey="ph"
                          name="pH"
                          stroke="#a78bfa"
                          dot={false}
                          strokeWidth={2}
                        />
                      )}
                      {anySeries(points, "water_quality_index") && (
                        <Line
                          yAxisId="a"
                          type="monotone"
                          dataKey="water_quality_index"
                          name="Water Q."
                          stroke="#f472b6"
                          dot={false}
                          strokeWidth={2}
                        />
                      )}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              {insights && (
                <div className="insights">
                  <strong>Insights</strong> (visible window)
                  <ul>
                    {insights.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}

          {last && !isTs && (
            <div className="banner">
              This build focuses on ThingSpeak. For pack/cell battery charts, use the Streamlit app locally or extend
              this React UI.
            </div>
          )}

          {!last && !err && status?.mode !== "thingspeak" && (
            <div className="banner">Connect to ThingSpeak in the sidebar to load telemetry.</div>
          )}
        </main>
      </div>
    </div>
  );
}
