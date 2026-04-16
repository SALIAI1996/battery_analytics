import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  Cell,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  XAxis,
  YAxis,
} from "recharts";
import { apiBase, apiGet, apiPost } from "./api";
import type { BatteryMetric, LatestResponse, StatusResponse } from "./types";
import "./App.css";

const MAX_POINTS = 4000;

const PIE_COLORS = ["#22d3ee", "#a78bfa", "#fbbf24", "#fb7185", "#4ade80", "#f472b6"];
const LINE_COLORS = ["#22d3ee", "#a78bfa", "#fbbf24", "#fb7185"];

function fmt(v: number | null | undefined, nd = 2): string {
  if (v === null || v === undefined) return "—";
  if (Number.isNaN(v)) return "—";
  return v.toFixed(nd);
}

function pct(v: number | null | undefined, nd = 0): string {
  if (v === null || v === undefined) return "—";
  if (Number.isNaN(v)) return "—";
  return `${v.toFixed(nd)}%`;
}

function clamp01(x: number) {
  if (Number.isNaN(x)) return 0;
  if (x < 0) return 0;
  if (x > 1) return 1;
  return x;
}

function clamp(x: number, lo: number, hi: number) {
  if (Number.isNaN(x)) return lo;
  if (x < lo) return lo;
  if (x > hi) return hi;
  return x;
}

type PieSpec = {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  fraction01: number; // 0..1 for the donut fill
  color: string;
};

export default function App() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [points, setPoints] = useState<BatteryMetric[]>([]);
  const [lastTs, setLastTs] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [channelId, setChannelId] = useState(3337776);
  const [readKey, setReadKey] = useState("");
  const [pollSec, setPollSec] = useState(15);
  const [initialN, setInitialN] = useState(500);
  const [viewN, setViewN] = useState<10 | 50 | 100>(100);
  const [tsChannelMeta, setTsChannelMeta] = useState<{ name?: string } | null>(null);

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
    document.title = "Battery Analytics";
  }, []);

  useEffect(() => {
    refreshStatus();
    const id = window.setInterval(refreshStatus, 5000);
    return () => window.clearInterval(id);
  }, [refreshStatus]);

  useEffect(() => {
    // Refresh the UI on a human-friendly cadence; backend poll interval is configurable (default 15s).
    const id = window.setInterval(pullLatest, 10_000);
    return () => window.clearInterval(id);
  }, [pullLatest]);

  /** Pull once when a device becomes active (reconnect resets ref via active_device_id going null). */
  const bootstrapPullFor = useRef<string | null>(null);
  useEffect(() => {
    if (!status?.streaming || !status?.active_device_id) {
      bootstrapPullFor.current = null;
      return;
    }
    if (bootstrapPullFor.current === status.active_device_id) return;
    bootstrapPullFor.current = status.active_device_id;
    void pullLatest();
  }, [status?.streaming, status?.active_device_id, pullLatest]);

  /** ThingSpeak channel status (name, etc.) — requires THINGSPEAK_READ_API_KEY on the API server. */
  useEffect(() => {
    if (!apiBase()) return;
    let cancelled = false;
    const load = async () => {
      try {
        const d = await apiGet<{ channel?: { name?: string } }>("/thingspeak/channel-status");
        if (!cancelled) setTsChannelMeta(d.channel ?? null);
      } catch {
        if (!cancelled) setTsChannelMeta(null);
      }
    };
    load();
    const t = window.setInterval(load, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, []);

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
      void pullLatest();
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

  const viewPoints = useMemo(() => (points.length > viewN ? points.slice(-viewN) : points), [points, viewN]);
  const last = viewPoints.length ? viewPoints[viewPoints.length - 1] : null;
  /** Show main dashboard whenever ThingSpeak is streaming — do not require `last` (fixes empty UI before first sample). */
  const showThingSpeakDashboard = Boolean(status?.mode === "thingspeak" && status?.streaming);

  const cellKeys = useMemo(() => {
    const s = new Set<string>();
    for (const p of viewPoints) {
      if (p.cell_voltages) Object.keys(p.cell_voltages).forEach((k) => s.add(k));
    }
    return Array.from(s).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  }, [viewPoints]);

  const pies = useMemo((): PieSpec[] => {
    // Defaults for scaling. You can tune these if your hardware differs.
    const maxCellV = 4.2;
    const maxTempC = 80;
    const maxCurrentA = 100;
    const v = (x: number | null | undefined) => (x == null || Number.isNaN(x) ? null : x);

    const soc = v(last?.soc_pct);
    const temp = v(last?.temperature_c);
    const cur = v(last?.current_a);

    const base: PieSpec[] = [
      {
        key: "soc",
        label: "SOC",
        value: soc,
        unit: "%",
        fraction01: clamp01(((soc ?? 0) / 100) || 0),
        color: "#34d399",
      },
    ];

    const cells = last?.cell_voltages ?? {};
    const cellOrder = (cellKeys.length ? cellKeys : ["V1", "V2", "V3", "V4"]).slice(0, 4);
    cellOrder.forEach((k, i) => {
      const cv = v(cells[k]);
      base.push({
        key: k,
        label: k.replace(/^V/i, "Cell "),
        value: cv,
        unit: "V",
        fraction01: clamp01(((cv ?? 0) / maxCellV) || 0),
        color: PIE_COLORS[i % PIE_COLORS.length]!,
      });
    });

    base.push(
      {
        key: "temp",
        label: "Temp",
        value: temp,
        unit: "°C",
        fraction01: clamp01(((clamp(temp ?? 0, 0, maxTempC)) / maxTempC) || 0),
        color: "#22d3ee",
      },
      {
        key: "current",
        label: "Current",
        value: cur,
        unit: "A",
        fraction01: clamp01(((clamp(Math.abs(cur ?? 0), 0, maxCurrentA)) / maxCurrentA) || 0),
        color: "#fbbf24",
      }
    );

    return base;
  }, [last, cellKeys]);

  const voltageSeries = useMemo(() => {
    const ks = (cellKeys.length ? cellKeys : ["V1", "V2", "V3", "V4"]).slice(0, 4);
    const rows = viewPoints.map((p, idx) => {
      const d = new Date(p.ts);
      const row: Record<string, string | number | undefined> = {
        idx,
        timeShort: d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        timeFull: d.toLocaleString(),
      };
      for (const k of ks) row[`cell_${k}`] = p.cell_voltages?.[k] ?? undefined;
      return row;
    });
    return { keys: ks, rows };
  }, [viewPoints, cellKeys]);

  return (
    <div className="app">
      <header className="header">
        <div className="header__row">
          <div>
            <h1>Battery Analytics</h1>
          </div>
          <div className="header__links">
            {apiBase() ? (
              <>
                <a className="header__pill" href={`${apiBase()}/health`} target="_blank" rel="noreferrer">
                  API health
                </a>
                <a className="header__pill" href={`${apiBase()}/docs`} target="_blank" rel="noreferrer">
                  OpenAPI
                </a>
              </>
            ) : (
              <span className="header__muted">Set VITE_API_URL on deploy</span>
            )}
          </div>
        </div>
        <p className="header__hint">
          Use <code className="mono">VITE_API_URL</code> = API origin only (e.g.{" "}
          <code className="mono">https://battery-analytics.onrender.com</code>), no <code className="mono">/api</code>{" "}
          suffix.
        </p>
      </header>

      <div className="layout">
        <aside className="panel">
          <h2>Data source</h2>
          {!baseConfigured && (
            <div className="banner warn">
              Set <span className="mono">VITE_API_URL</span> to your Render API URL before deploy. Local dev:{" "}
              <span className="mono">vite</span> + <span className="mono">uvicorn</span> (proxy <span className="mono">/api</span>
              ).
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
              placeholder="Or set THINGSPEAK_READ_API_KEY on the server"
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
          <div className="field">
            <label htmlFor="view">Show last N records</label>
            <select
              id="view"
              value={viewN}
              onChange={(e) => setViewN(Number(e.target.value) as 10 | 50 | 100)}
            >
              <option value={10}>Last 10</option>
              <option value={50}>Last 50</option>
              <option value={100}>Last 100</option>
            </select>
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

          <div className="panel__help">
            <strong>Tip</strong>
            <p className="panel__help-p">
              Keep your ThingSpeak read key on the server as <span className="mono">THINGSPEAK_READ_API_KEY</span> to
              avoid exposing it in the browser.
            </p>
          </div>
        </aside>

        <main className="main">
          <div className="status-strip">
            <div className="status-pill">
              <span className="status-pill__k">Mode</span>
              <span className="status-pill__v">{status?.mode ?? "—"}</span>
            </div>
            <div className="status-pill">
              <span className="status-pill__k">Live</span>
              <span className={`status-pill__v ${status?.streaming ? "status-pill__v--on" : ""}`}>
                {status?.streaming ? "Streaming" : "Idle"}
              </span>
            </div>
            <div className="status-pill status-pill--wide">
              <span className="status-pill__k">Device</span>
              <span className="status-pill__v mono">{status?.active_device_id ?? "—"}</span>
            </div>
            {tsChannelMeta?.name && (
              <div className="status-pill status-pill--grow">
                <span className="status-pill__k">ThingSpeak</span>
                <span className="status-pill__v">{tsChannelMeta.name}</span>
              </div>
            )}
            {(points.length > 0 || (status?.metrics_buffer_len ?? 0) > 0) && (
              <div className="status-pill">
                <span className="status-pill__k">Samples</span>
                <span className="status-pill__v">
                  {points.length}
                  {status?.mode === "thingspeak" && status.metrics_buffer_len != null && (
                    <span className="status-pill__hint"> (API buffer {status.metrics_buffer_len})</span>
                  )}
                </span>
              </div>
            )}
          </div>

          {!points.length && status?.mode === "thingspeak" && status.streaming && (
            <div className="thingspeak-wait">
              {status.thingspeak?.last_error ? (
                <div className="banner banner--error">
                  <strong>ThingSpeak polling error.</strong> The backend could not read feeds for this channel.{" "}
                  <span className="mono wrap-break">{status.thingspeak.last_error}</span>
                  <ul className="thingspeak-wait__list">
                    <li>
                      Use the <strong>Read API key</strong> for <em>this</em> channel (not the write key). Paste it in
                      the sidebar or set <span className="mono">THINGSPEAK_READ_API_KEY</span> on the API server for the
                      same channel ID.
                    </li>
                    <li>
                      Private channels return HTTP 400 if the key does not match — the buffer stays empty even while
                      “Streaming” is on.
                    </li>
                  </ul>
                </div>
              ) : (status.metrics_buffer_len ?? 0) > 0 ? (
                <div className="banner banner--warn">
                  <strong>API has data but the browser has not synced yet.</strong> Try refreshing the page. If it
                  persists, check the browser network tab for <span className="mono">/metrics/latest</span> (CORS /
                  <span className="mono">VITE_API_URL</span>).
                </div>
              ) : (
                <div className="banner banner--pulse">
                  <strong>Waiting for ThingSpeak rows…</strong> The channel returned{" "}
                  <strong>{status.thingspeak?.last_feed_count ?? 0}</strong> feed row(s) on the last successful poll.
                  {status.thingspeak && status.thingspeak.polls_failed > 0 && (
                    <> Poll failures: {status.thingspeak.polls_failed}.</>
                  )}
                  <ul className="thingspeak-wait__list">
                    <li>If the count is 0, the channel has no entries yet — publish at least one update from your device.</li>
                    <li>
                      Confirm <span className="mono">VITE_API_URL</span> points at your Render API (scheme{" "}
                      <span className="mono">https://</span>), not the Vercel UI URL.
                    </li>
                  </ul>
                </div>
              )}
            </div>
          )}

          {showThingSpeakDashboard && (
            <>
              <section className="section section--minimal">
                <div className="pie-min-grid" aria-label="Battery pie charts">
                  {pies.map((p) => (
                    <div key={p.key} className="pie-tile">
                      <div className="pie-tile__label">{p.label}</div>
                      <div className="pie-tile__chart">
                        <ResponsiveContainer width="100%" height={240}>
                          <PieChart>
                            <Pie
                              data={[
                                { name: p.key, value: p.fraction01 * 100 },
                                { name: "rest", value: 100 - p.fraction01 * 100 },
                              ]}
                              dataKey="value"
                              innerRadius={78}
                              outerRadius={102}
                              paddingAngle={2}
                              startAngle={90}
                              endAngle={-270}
                              stroke="rgba(15,22,32,0.0)"
                              isAnimationActive={true}
                            >
                              <Cell fill={p.color} />
                              <Cell fill="rgba(148, 163, 184, 0.18)" />
                            </Pie>
                            <Tooltip />
                          </PieChart>
                        </ResponsiveContainer>
                        <div className="pie-tile__center">
                          <div className="pie-tile__value">
                            {p.unit === "%" ? (p.value != null ? pct(p.value, 0) : "—") : fmt(p.value, p.unit === "V" ? 2 : 1)}
                          </div>
                          <div className="pie-tile__unit">{p.unit === "%" ? "" : p.unit}</div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="section section--minimal">
                <div className="line-card">
                  <div className="line-card__label">Cell voltages</div>
                  {voltageSeries.rows.length === 0 ? (
                    <div className="chart-empty">No samples yet.</div>
                  ) : (
                    <ResponsiveContainer width="100%" height={320}>
                      <ComposedChart data={voltageSeries.rows} margin={{ top: 12, right: 12, left: 4, bottom: 4 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#243044" vertical={false} />
                        <XAxis dataKey="timeShort" tick={{ fill: "#8b9cb3", fontSize: 11 }} minTickGap={24} />
                        <YAxis tick={{ fill: "#8b9cb3", fontSize: 11 }} />
                        <Tooltip />
                        <Legend />
                        {voltageSeries.keys.map((k, i) => (
                          <Line
                            key={k}
                            type="monotone"
                            dataKey={`cell_${k}`}
                            name={k.replace(/^V/i, "Cell ")}
                            stroke={LINE_COLORS[i % LINE_COLORS.length]!}
                            strokeWidth={2.2}
                            dot={false}
                            isAnimationActive={voltageSeries.rows.length < 500}
                          />
                        ))}
                      </ComposedChart>
                    </ResponsiveContainer>
                  )}
                </div>
              </section>
            </>
          )}

          {!showThingSpeakDashboard && !err && (
            <div className="banner">Connect to ThingSpeak in the sidebar to load telemetry.</div>
          )}
        </main>
      </div>
    </div>
  );
}
