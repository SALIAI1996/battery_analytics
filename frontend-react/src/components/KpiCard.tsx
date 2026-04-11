import { useId } from "react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  YAxis,
} from "recharts";

type Props = {
  title: string;
  unit: string;
  value: string;
  subtitle?: string;
  tone?: "default" | "good" | "mid" | "warn";
  sparkline: { v: number }[];
  min?: number;
  max?: number;
  deltaLabel?: string;
  footnote?: string;
};

export function KpiCard({
  title,
  unit,
  value,
  subtitle,
  tone = "default",
  sparkline,
  min,
  max,
  deltaLabel,
  footnote,
}: Props) {
  const gradId = useId().replace(/:/g, "");
  const hasRange = min != null && max != null && max > min;
  const last = sparkline.length ? sparkline[sparkline.length - 1]!.v : null;
  const pct =
    hasRange && last != null ? ((last - min!) / (max! - min!)) * 100 : 50;

  return (
    <div className={`kpi-card kpi-card--${tone}`}>
      <div className="kpi-card__head">
        <span className="kpi-card__title">{title}</span>
        <span className="kpi-card__unit">{unit}</span>
      </div>
      <div className="kpi-card__value-row">
        <span className="kpi-card__value">{value}</span>
        {deltaLabel && <span className="kpi-card__delta">{deltaLabel}</span>}
      </div>
      {subtitle && <p className="kpi-card__sub">{subtitle}</p>}
      {sparkline.length > 1 && (
        <div className="kpi-card__spark">
          <ResponsiveContainer width="100%" height={44}>
            <AreaChart data={sparkline} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="currentColor" stopOpacity={0.35} />
                  <stop offset="100%" stopColor="currentColor" stopOpacity={0} />
                </linearGradient>
              </defs>
              <YAxis hide domain={["dataMin - 1", "dataMax + 1"]} />
              <Area
                type="monotone"
                dataKey="v"
                stroke="currentColor"
                strokeWidth={1.5}
                fill={`url(#${gradId})`}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
      {hasRange && (
        <div className="kpi-card__range" title={footnote}>
          <span className="kpi-card__range-min">{min!.toFixed(1)}</span>
          <div className="kpi-card__range-track">
            <span className="kpi-card__range-fill" style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
            <span className="kpi-card__range-dot" style={{ left: `${Math.min(100, Math.max(0, pct))}%` }} />
          </div>
          <span className="kpi-card__range-max">{max!.toFixed(1)}</span>
        </div>
      )}
      {footnote && <p className="kpi-card__note">{footnote}</p>}
    </div>
  );
}
