type Row = { name?: string; value?: number; color?: string; payload?: { timeFull?: string; timeShort?: string } };

/** Rich tooltip for time-series charts */
export function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Row[];
}) {
  if (!active || !payload?.length) return null;
  const datum = payload[0]?.payload;
  const timeLabel = datum?.timeFull ?? datum?.timeShort ?? "";
  return (
    <div className="chart-tooltip">
      {timeLabel && <div className="chart-tooltip__time">{timeLabel}</div>}
      <ul className="chart-tooltip__rows">
        {payload.map((p: Row, i: number) => (
          <li key={i} style={{ borderLeftColor: p.color || "var(--accent)" }}>
            <span className="chart-tooltip__name">{p.name}</span>
            <span className="chart-tooltip__val">
              {p.value != null && typeof p.value === "number" ? p.value.toFixed(2) : "—"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
