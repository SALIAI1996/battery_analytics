import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Area,
  Brush,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ChartTooltip } from "./components/ChartTooltip";
import { KpiCard } from "./components/KpiCard";
import { apiBase, apiGet, apiPost } from "./api";
import {
  formatDelta,
  numericSeries,
  phInterpretation,
  seriesStats,
} from "./metrics";
import type { BatteryMetric, LatestResponse, StatusResponse } from "./types";
import "./App.css";

const MAX_POINTS = 4000;
const SPARK_POINTS = 80;

function fmt(v: number | null | undefined, nd = 2): string {
  if (v === null || v === undefined) return "—";
  if (Number.isNaN(v)) return "—";
  return v.toFixed(nd);
}

function anySeries(points: BatteryMetric[], key: keyof BatteryMetric): boolean {
  return points.some((p) => p[key] !== null && p[key] !== undefined);
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
    return points.map((p, idx) => {
      const d = new Date(p.ts);
      return {
        idx,
        t: p.ts,
        timeShort: d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        timeFull: d.toLocaleString(),
        temperature_c: p.temperature_c,
        humidity_pct: p.humidity_pct ?? undefined,
        tds_ppm: p.tds_ppm ?? undefined,
        ph: p.ph ?? undefined,
        water_quality_index: p.water_quality_index ?? undefined,
      };
    });
  }, [points]);

  const tempSt = useMemo(() => seriesStats(numericSeries(points, (p) => p.temperature_c)), [points]);
  const humSt = useMemo(() => seriesStats(numericSeries(points, (p) => p.humidity_pct)), [points]);
  const tdsSt = useMemo(() => seriesStats(numericSeries(points, (p) => p.tds_ppm)), [points]);
  const phSt = useMemo(() => seriesStats(numericSeries(points, (p) => p.ph)), [points]);
  const wqSt = useMemo(() => seriesStats(numericSeries(points, (p) => p.water_quality_index)), [points]);

  const insights = useMemo(() => {
    if (!isTs || !points.length) return null;
    const temps = numericSeries(points, (p) => p.temperature_c);
    const phs = numericSeries(points, (p) => p.ph);
    const tds = numericSeries(points, (p) => p.tds_ppm);
    const lines: string[] = [];
    if (temps.length) {
      lines.push(
        `Temperature range in view: ${Math.min(...temps).toFixed(2)} – ${Math.max(...temps).toFixed(2)} °C`
      );
    }
    if (phs.length) {
      lines.push(`pH range in view: ${Math.min(...phs).toFixed(2)} – ${Math.max(...phs).toFixed(2)}`);
    }
    if (tds.length) {
      lines.push(`TDS range in view: ${Math.min(...tds).toFixed(0)} – ${Math.max(...tds).toFixed(0)} ppm`);
    }
    return lines.length ? lines : null;
  }, [isTs, points]);

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
            <h1>Environmental analytics</h1>
            <p className="header__lede">
              Live water &amp; environment telemetry from ThingSpeak — interactive charts, ranges, and at-a-glance
              KPIs.
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
            <strong>Reading the dashboard</strong>
            <ul>
              <li>
                <strong>KPI cards</strong> show the latest value, spark trend, and where the current reading sits between
                min/max in the visible window.
              </li>
              <li>
                <strong>Brush</strong> (grey bar under a chart) lets you zoom and pan the time range.
              </li>
              <li>
                <strong>pH band</strong> highlights ~6.5–8.5 as a common “near neutral” band (informational only).
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
            {points.length > 0 && (
              <div className="status-pill">
                <span className="status-pill__k">Samples</span>
                <span className="status-pill__v">{points.length}</span>
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
            <div className="banner banner--pulse">Waiting for first samples from ThingSpeak…</div>
          )}

          {last && isTs && (
            <>
              <section className="section">
                <h2 className="section__title">At a glance</h2>
                <p className="section__sub">Latest reading vs min–max in the chart window (use brush below to change the window).</p>
                <div className="kpi-grid">
                  <KpiCard
                    title="Temperature"
                    unit="°C"
                    value={fmt(last.temperature_c)}
                    sparkline={spark(numericSeries(points, (p) => p.temperature_c))}
                    min={tempSt?.min}
                    max={tempSt?.max}
                    deltaLabel={
                      tempSt && tempSt.delta !== 0
                        ? formatDelta(tempSt.delta, "°C") + " window"
                        : undefined
                    }
                    footnote="Typical comfort ~20–26 °C (context-dependent)"
                  />
                  <KpiCard
                    title="Humidity"
                    unit="%"
                    value={fmt(last.humidity_pct ?? undefined)}
                    sparkline={spark(numericSeries(points, (p) => p.humidity_pct))}
                    min={humSt?.min}
                    max={humSt?.max}
                    deltaLabel={
                      humSt && humSt.delta !== 0 ? formatDelta(humSt.delta, "%") + " window" : undefined
                    }
                  />
                  <KpiCard
                    title="TDS"
                    unit="ppm"
                    value={fmt(last.tds_ppm ?? undefined, 1)}
                    sparkline={spark(numericSeries(points, (p) => p.tds_ppm))}
                    min={tdsSt?.min}
                    max={tdsSt?.max}
                    deltaLabel={
                      tdsSt && tdsSt.delta !== 0 ? formatDelta(tdsSt.delta, "ppm", 0) + " window" : undefined
                    }
                    footnote="Total dissolved solids — calibrate to your application"
                  />
                  <KpiCard
                    title="pH"
                    unit=""
                    value={fmt(last.ph ?? undefined)}
                    subtitle={last.ph != null ? phInterpretation(last.ph).label : undefined}
                    tone={last.ph != null ? phInterpretation(last.ph).tone : "default"}
                    sparkline={spark(numericSeries(points, (p) => p.ph))}
                    min={phSt?.min}
                    max={phSt?.max}
                    deltaLabel={
                      phSt && phSt.delta !== 0 ? formatDelta(phSt.delta, "pH") + " window" : undefined
                    }
                    footnote="Band 6.5–8.5 shown on chart as reference"
                  />
                  <KpiCard
                    title="Water quality"
                    unit="idx"
                    value={fmt(last.water_quality_index ?? undefined)}
                    sparkline={spark(numericSeries(points, (p) => p.water_quality_index))}
                    min={wqSt?.min}
                    max={wqSt?.max}
                    footnote="Field 5 on ThingSpeak (if configured)"
                  />
                </div>
              </section>

              {(anySeries(points, "temperature_c") || anySeries(points, "humidity_pct")) && (
                <section className="section">
                  <h2 className="section__title">Climate — temperature & humidity</h2>
                  <p className="section__sub">Area emphasis on trends; drag the brush to focus a time range.</p>
                  <div className="chart-wrap chart-wrap--tall">
                    <ResponsiveContainer width="100%" height={420}>
                      <ComposedChart data={chartData} margin={{ top: 12, right: 12, left: 4, bottom: 4 }}>
                        <defs>
                          <linearGradient id="tempFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#3d9cf0" stopOpacity={0.35} />
                            <stop offset="100%" stopColor="#3d9cf0" stopOpacity={0} />
                          </linearGradient>
                          <linearGradient id="humFill" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#34d399" stopOpacity={0.3} />
                            <stop offset="100%" stopColor="#34d399" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#243044" vertical={false} />
                        <XAxis dataKey="timeShort" tick={{ fill: "#8b9cb3", fontSize: 11 }} minTickGap={24} />
                        <YAxis
                          yAxisId="l"
                          tick={{ fill: "#8b9cb3", fontSize: 11 }}
                          label={{ value: "°C", angle: -90, position: "insideLeft", fill: "#8b9cb3" }}
                        />
                        <YAxis
                          yAxisId="r"
                          orientation="right"
                          tick={{ fill: "#8b9cb3", fontSize: 11 }}
                          label={{ value: "% RH", angle: 90, position: "insideRight", fill: "#8b9cb3" }}
                        />
                        <Tooltip content={<ChartTooltip />} />
                        <Legend />
                        {anySeries(points, "temperature_c") && (
                          <Area
                            yAxisId="l"
                            type="monotone"
                            dataKey="temperature_c"
                            name="Temperature °C"
                            stroke="#3d9cf0"
                            fill="url(#tempFill)"
                            strokeWidth={2}
                            dot={false}
                            isAnimationActive={points.length < 500}
                          />
                        )}
                        {anySeries(points, "humidity_pct") && (
                          <Area
                            yAxisId="r"
                            type="monotone"
                            dataKey="humidity_pct"
                            name="Humidity %"
                            stroke="#34d399"
                            fill="url(#humFill)"
                            strokeWidth={2}
                            dot={false}
                            isAnimationActive={points.length < 500}
                          />
                        )}
                        <Brush dataKey="idx" height={28} stroke="#3d9cf0" fill="rgba(36,48,68,0.5)" travellerWidth={8} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </section>
              )}

              {(anySeries(points, "tds_ppm") || anySeries(points, "ph") || anySeries(points, "water_quality_index")) && (
                <section className="section">
                  <h2 className="section__title">Water chemistry</h2>
                  <p className="section__sub">
                    pH reference band (6.5–8.5) is a common informational range — not a compliance line. TDS scale
                    depends on calibration.
                  </p>
                  <div className="chart-wrap chart-wrap--tall">
                    <ResponsiveContainer width="100%" height={440}>
                      <ComposedChart data={chartData} margin={{ top: 12, right: 16, left: 4, bottom: 4 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#243044" vertical={false} />
                        <XAxis dataKey="timeShort" tick={{ fill: "#8b9cb3", fontSize: 11 }} minTickGap={24} />
                        <YAxis
                          yAxisId="a"
                          tick={{ fill: "#8b9cb3", fontSize: 11 }}
                          label={{ value: "TDS / WQ", angle: -90, position: "insideLeft", fill: "#8b9cb3" }}
                        />
                        <YAxis
                          yAxisId="b"
                          orientation="right"
                          domain={[0, 14]}
                          tick={{ fill: "#8b9cb3", fontSize: 11 }}
                          label={{ value: "pH", angle: 90, position: "insideRight", fill: "#8b9cb3" }}
                        />
                        {anySeries(points, "ph") && (
                          <>
                            <ReferenceArea
                              yAxisId="b"
                              y1={6.5}
                              y2={8.5}
                              strokeOpacity={0}
                              fill="#34d399"
                              fillOpacity={0.12}
                            />
                            <ReferenceLine yAxisId="b" y={7} stroke="#94a3b8" strokeDasharray="4 4" />
                          </>
                        )}
                        <Tooltip content={<ChartTooltip />} />
                        <Legend />
                        {anySeries(points, "tds_ppm") && (
                          <Line
                            yAxisId="a"
                            type="monotone"
                            dataKey="tds_ppm"
                            name="TDS (ppm)"
                            stroke="#fbbf24"
                            dot={false}
                            strokeWidth={2}
                            isAnimationActive={points.length < 500}
                          />
                        )}
                        {anySeries(points, "ph") && (
                          <Line
                            yAxisId="b"
                            type="monotone"
                            dataKey="ph"
                            name="pH"
                            stroke="#c4b5fd"
                            dot={false}
                            strokeWidth={2.5}
                            isAnimationActive={points.length < 500}
                          />
                        )}
                        {anySeries(points, "water_quality_index") && (
                          <Line
                            yAxisId="a"
                            type="monotone"
                            dataKey="water_quality_index"
                            name="Water quality"
                            stroke="#f472b6"
                            dot={false}
                            strokeWidth={2}
                            strokeDasharray="6 4"
                            isAnimationActive={points.length < 500}
                          />
                        )}
                        <Brush dataKey="idx" height={28} stroke="#a78bfa" fill="rgba(36,48,68,0.5)" travellerWidth={8} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </section>
              )}

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

          {last && !isTs && (
            <div className="banner">
              Non–ThingSpeak telemetry is available from the API; this dashboard is optimized for ThingSpeak fields.
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
