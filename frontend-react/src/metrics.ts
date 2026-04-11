/** Helpers for dashboard stats and qualitative bands (water monitoring). */

export function numericSeries<T>(arr: T[], pick: (x: T) => number | null | undefined): number[] {
  return arr.map(pick).filter((x): x is number => x != null && !Number.isNaN(x));
}

export function seriesStats(values: number[]) {
  if (!values.length) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const sum = values.reduce((a, b) => a + b, 0);
  const avg = sum / values.length;
  const first = values[0]!;
  const last = values[values.length - 1]!;
  const delta = last - first;
  return { min, max, avg, first, last, delta, span: max - min };
}

/** Rough pH interpretation for display (not a regulatory claim). */
export function phInterpretation(ph: number): { label: string; tone: "good" | "mid" | "warn" } {
  if (ph < 6.5) return { label: "Acidic", tone: "warn" };
  if (ph > 8.5) return { label: "Alkaline", tone: "mid" };
  return { label: "Near neutral", tone: "good" };
}

export function formatDelta(delta: number, unit: string, nd = 2): string {
  const sign = delta > 0 ? "+" : "";
  return `${sign}${delta.toFixed(nd)} ${unit}`;
}
