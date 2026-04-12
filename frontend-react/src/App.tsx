import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Brush, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartTooltip } from "./components/ChartTooltip";
import { KpiCard } from "./components/KpiCard";
import { apiBase, apiGet, apiPost } from "./api";
import { formatDelta, numericSeries, seriesStats } from "./metrics";
import type { BatteryMetric, LatestResponse, StatusResponse } from "./types";
import "./App.css";

const MAX_POINTS = 4000;
const SPARK_POINTS = 80;

/** Distinct stroke colors for per-cell voltage lines (cycles if more cells). */
const CELL_LINE_COLORS = ["#22d3ee", "#a78bfa", "#fbbf24", "#fb7185", "#4ade80", "#f472b6"];

function fmt(v: number | null | undefined, nd = 2): string {
  if (v === null || v === undefined) return "—";
  if (Number.isNaN(v)) return "—";
  return v.toFixed(nd);
}

function spark(values: number[], max = SPARK_POINTS) {
  const slice = values.length > max ? values.slice(-max) : values;
  return slice.map((v) => ({ v }));
}

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
    const id = window.setInterval(pullLatest, 1500);
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
  /** Show main dashboard whenever ThingSpeak is streaming — do not require `last` (fixes empty UI before first sample). */
  const showThingSpeakDashboard = Boolean(status?.mode === "thingspeak" && status?.streaming);

  const hasBatteryPack = useMemo(
    () => points.some((p) => p.cell_voltages && Object.keys(p.cell_voltages).length > 0),
    [points]
  );

  const cellKeys = useMemo(() => {
    const s = new Set<string>();
    for (const p of points) {
      if (p.cell_voltages) Object.keys(p.cell_voltages).forEach((k) => s.add(k));
    }
    return Array.from(s).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  }, [points]);

  const chartData = useMemo(() => {
    return points.map((p, idx) => {
      const d = new Date(p.ts);
      const row: Record<string, string | number | undefined> = {
        idx,
        t: p.ts,
        timeShort: d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        timeFull: d.toLocaleString(),
        temperature_c: p.temperature_c,
        humidity_pct: p.humidity_pct ?? undefined,
        tds_ppm: p.tds_ppm ?? undefined,
        ph: p.ph ?? undefined,
        water_quality_index: p.water_quality_index ?? undefined,
        voltage_v: p.voltage_v,
        current_a: p.current_a,
        soc_pct: p.soc_pct ?? undefined,
      };
      for (const k of cellKeys) {
        row[`cell_${k}`] = p.cell_voltages?.[k] ?? undefined;
      }
      return row;
    });
  }, [points, cellKeys]);

  const tempSt = useMemo(() => seriesStats(numericSeries(points, (p) => p.temperature_c)), [points]);
  const packVSt = useMemo(() => seriesStats(numericSeries(points, (p) => p.voltage_v)), [points]);
  const currSt = useMemo(() => seriesStats(numericSeries(points, (p) => p.current_a)), [points]);
  const socSt = useMemo(() => seriesStats(numericSeries(points, (p) => p.soc_pct)), [points]);

  const insights = useMemo(() => {
    if (!showThingSpeakDashboard || !points.length) return null;
    const lines: string[] = [];
    const volts = numericSeries(points, (p) => p.voltage_v);
    if (volts.length && volts.some((v) => v > 0.001)) {
      lines.push(
        `Pack voltage range in view: ${Math.min(...volts).toFixed(2)} – ${Math.max(...volts).toFixed(2)} V`
      );
    }
    const lastPt = points[points.length - 1]!;
    if (lastPt.cell_voltages) {
      const xs = Object.values(lastPt.cell_voltages);
      if (xs.length > 1) {
        const spread = Math.max(...xs) - Math.min(...xs);
        lines.push(`Latest cell spread: ${spread.toFixed(3)} V`);
      }
    }
    const temps = numericSeries(points, (p) => p.temperature_c);
    if (temps.length) {
      lines.push(
        `BMS temperature range in view: ${Math.min(...temps).toFixed(2)} – ${Math.max(...temps).toFixed(2)} °C`
      );
    }
    return lines.length ? lines : null;
  }, [showThingSpeakDashboard, points]);

  const timeSpanLabel = useMemo(() => {
    if (points.length < 2) return null;
    const a = new Date(points[0]!.ts);
    const b = new Date(points[points.length - 1]!.ts);
    const mins = (b.getTime() - a.getTime()) / 60000;
    if (mins < 120) return `${Math.round(mins)} min window`;
    if (mins < 2880) return `${(mins / 60).toFixed(1)} h window`;
    return `${(mins / 1440).toFixed(1)} d window`;
  }, [points]);

  const lastSampleLabel = last ? new Date(last.ts).toLocaleString() : null;

  return (
    <div className="app">
      <header className="header">
        <div className="header__row">
          <div>
            <h1>Battery Analytics</h1>
            <p className="header__lede">
              Pack and per-cell voltages, current, temperature, and SOC from ThingSpeak (BMS text such as{" "}
              <code className="mono">V1=3.7,…,I=1.2A,T=30C,SOC=75%</code> in any field).
            </p>
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
        <p className="header__hint header__hint--meta">
          UI bundle: <span className="mono">{__BUILD_TIME__}</span> — if this does not change after a deploy, hard-refresh
          (Shift+Reload) or clear site data; API calls use no-cache fetch.
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
            <strong>ThingSpeak read key</strong>
            <p className="panel__help-p">
              The <strong>Read API key must belong to the channel ID</strong> you enter above. If the key is for a
              different channel, the API cannot load feeds and charts stay empty. Set the same key on the server as{" "}
              <span className="mono">THINGSPEAK_READ_API_KEY</span> (e.g. Render) or paste it here when connecting so{" "}
              <span className="mono">/thingspeak/channel-status</span> and polling work.
            </p>
            <strong>Reading the dashboard</strong>
            <ul>
              <li>
                <strong>KPI cards</strong> show the latest pack and BMS values; sparklines update as samples arrive.
              </li>
              <li>
                <strong>Brush</strong> (grey bar under a chart) zooms and pans the time range.
              </li>
            </ul>
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
            {timeSpanLabel && (
              <div className="status-pill">
                <span className="status-pill__k">Window</span>
                <span className="status-pill__v">{timeSpanLabel}</span>
              </div>
            )}
            {lastSampleLabel && (
              <div className="status-pill status-pill--grow">
                <span className="status-pill__k">Last sample</span>
                <span className="status-pill__v">{lastSampleLabel}</span>
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
                  <section className="section">
                    <h2 className="section__title">Battery pack</h2>
                    <p className="section__sub">
                      Parsed from ThingSpeak fields containing BMS text (e.g.{" "}
                      <code className="mono">V1=3.7,…,I=1.2A,T=30C,SOC=75%</code>). Use the brush on charts to narrow
                      time.
                    </p>
                    <div className="kpi-grid">
                      <KpiCard
                        title="Pack voltage"
                        unit="V"
                        value={last ? fmt(last.voltage_v) : "—"}
                        sparkline={spark(numericSeries(points, (p) => p.voltage_v))}
                        min={packVSt?.min}
                        max={packVSt?.max}
                        deltaLabel={
                          packVSt && packVSt.delta !== 0
                            ? formatDelta(packVSt.delta, "V") + " window"
                            : undefined
                        }
                        footnote="Sum of cell voltages when cells are present"
                      />
                      <KpiCard
                        title="Current"
                        unit="A"
                        value={last ? fmt(last.current_a) : "—"}
                        sparkline={spark(numericSeries(points, (p) => p.current_a))}
                        min={currSt?.min}
                        max={currSt?.max}
                        deltaLabel={
                          currSt && currSt.delta !== 0
                            ? formatDelta(currSt.delta, "A") + " window"
                            : undefined
                        }
                      />
                      <KpiCard
                        title="BMS temperature"
                        unit="°C"
                        value={last ? fmt(last.temperature_c) : "—"}
                        sparkline={spark(numericSeries(points, (p) => p.temperature_c))}
                        min={tempSt?.min}
                        max={tempSt?.max}
                        deltaLabel={
                          tempSt && tempSt.delta !== 0
                            ? formatDelta(tempSt.delta, "°C") + " window"
                            : undefined
                        }
                      />
                      <KpiCard
                        title="State of charge"
                        unit="%"
                        value={last != null && last.soc_pct != null ? fmt(last.soc_pct, 0) : "—"}
                        sparkline={spark(numericSeries(points, (p) => p.soc_pct))}
                        min={socSt?.min}
                        max={socSt?.max}
                        deltaLabel={
                          socSt && socSt.delta !== 0 ? formatDelta(socSt.delta, "%", 0) + " window" : undefined
                        }
                      />
                    </div>
                    {points.length > 0 && !hasBatteryPack && (
                      <div className="banner warn" style={{ marginTop: "1rem" }}>
                        <strong>No BMS line detected in feeds yet.</strong> Put telemetry such as{" "}
                        <code className="mono">V1=3.7,V2=…,I=1.2A,T=30C,SOC=75%</code> into any ThingSpeak field so pack
                        and cells populate (raw env-only fields show temperature as field1 only).
                      </div>
                    )}
                    {cellKeys.length > 0 && last && (
                      <div className="battery-cells" aria-label="Latest cell voltages">
                        {cellKeys.map((k) => (
                          <div key={k} className="battery-cell-pill">
                            <span className="battery-cell-pill__k">{k}</span>
                            <span className="battery-cell-pill__v">
                              {fmt(last.cell_voltages?.[k], 2)} V
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </section>

                  <section className="section">
                    <h2 className="section__title">Pack &amp; cell voltages</h2>
                    <p className="section__sub">Pack total and per-cell traces (volts).</p>
                    <div className="chart-wrap chart-wrap--tall">
                      {points.length === 0 ? (
                        <div className="chart-empty">
                          No time-series samples yet. After ThingSpeak returns rows, voltage traces appear here.
                        </div>
                      ) : (
                        <ResponsiveContainer width="100%" height={420}>
                          <ComposedChart data={chartData} margin={{ top: 12, right: 12, left: 4, bottom: 4 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#243044" vertical={false} />
                            <XAxis dataKey="timeShort" tick={{ fill: "#8b9cb3", fontSize: 11 }} minTickGap={24} />
                            <YAxis
                              tick={{ fill: "#8b9cb3", fontSize: 11 }}
                              domain={["auto", "auto"]}
                              label={{ value: "V", angle: -90, position: "insideLeft", fill: "#8b9cb3" }}
                            />
                            <Tooltip content={<ChartTooltip />} />
                            <Legend />
                            <Line
                              type="monotone"
                              dataKey="voltage_v"
                              name="Pack V"
                              stroke="#e8edf5"
                              strokeWidth={2.5}
                              dot={false}
                              isAnimationActive={points.length < 500}
                            />
                            {cellKeys.map((k, i) => (
                              <Line
                                key={k}
                                type="monotone"
                                dataKey={`cell_${k}`}
                                name={`${k}`}
                                stroke={CELL_LINE_COLORS[i % CELL_LINE_COLORS.length]}
                                strokeWidth={1.75}
                                dot={false}
                                isAnimationActive={points.length < 500}
                              />
                            ))}
                            <Brush dataKey="idx" height={28} stroke="#22d3ee" fill="rgba(36,48,68,0.5)" travellerWidth={8} />
                          </ComposedChart>
                        </ResponsiveContainer>
                      )}
                    </div>
                  </section>

                  <section className="section">
                    <h2 className="section__title">Current &amp; state of charge</h2>
                    <p className="section__sub">Amperes and SOC (%).</p>
                    <div className="chart-wrap chart-wrap--tall">
                      {points.length === 0 ? (
                        <div className="chart-empty">
                          No samples yet — current and SOC lines appear when your channel sends data.
                        </div>
                      ) : (
                        <ResponsiveContainer width="100%" height={360}>
                          <ComposedChart data={chartData} margin={{ top: 12, right: 16, left: 4, bottom: 4 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#243044" vertical={false} />
                            <XAxis dataKey="timeShort" tick={{ fill: "#8b9cb3", fontSize: 11 }} minTickGap={24} />
                            <YAxis
                              yAxisId="a"
                              tick={{ fill: "#8b9cb3", fontSize: 11 }}
                              label={{ value: "A", angle: -90, position: "insideLeft", fill: "#8b9cb3" }}
                            />
                            <YAxis
                              yAxisId="b"
                              orientation="right"
                              domain={[0, 100]}
                              tick={{ fill: "#8b9cb3", fontSize: 11 }}
                              label={{ value: "% SOC", angle: 90, position: "insideRight", fill: "#8b9cb3" }}
                            />
                            <Tooltip content={<ChartTooltip />} />
                            <Legend />
                            <Line
                              yAxisId="a"
                              type="monotone"
                              dataKey="current_a"
                              name="Current A"
                              stroke="#fbbf24"
                              strokeWidth={2}
                              dot={false}
                              isAnimationActive={points.length < 500}
                            />
                            <Line
                              yAxisId="b"
                              type="monotone"
                              dataKey="soc_pct"
                              name="SOC %"
                              stroke="#34d399"
                              strokeWidth={2}
                              dot={false}
                              isAnimationActive={points.length < 500}
                            />
                            <Brush dataKey="idx" height={28} stroke="#fbbf24" fill="rgba(36,48,68,0.5)" travellerWidth={8} />
                          </ComposedChart>
                        </ResponsiveContainer>
                      )}
                    </div>
                  </section>

              {insights && (
                <section className="section">
                  <h2 className="section__title">Summary for visible window</h2>
                  <ul className="insight-list">
                    {insights.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </section>
              )}
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
