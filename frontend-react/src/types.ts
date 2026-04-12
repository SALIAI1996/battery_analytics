export interface ThingSpeakStatus {
  last_error: string | null;
  last_feed_count: number;
  polls_succeeded: number;
  polls_failed: number;
}

export interface StatusResponse {
  active_device_id: string | null;
  connected: boolean;
  streaming: boolean;
  mode: "serial" | "sim" | "none" | "thingspeak";
  /** Rows the API has buffered for GET /metrics/latest */
  metrics_buffer_len?: number;
  thingspeak?: ThingSpeakStatus | null;
}

export interface BatteryMetric {
  ts: string;
  device_id: string;
  voltage_v: number;
  current_a: number;
  temperature_c: number;
  soc_pct?: number | null;
  cell_voltages?: Record<string, number> | null;
  humidity_pct?: number | null;
  tds_ppm?: number | null;
  ph?: number | null;
  water_quality_index?: number | null;
  raw_line?: string | null;
  source: string;
}

export interface LatestResponse {
  device_id: string;
  points: BatteryMetric[];
}
