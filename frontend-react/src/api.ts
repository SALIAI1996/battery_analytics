/** Base URL for FastAPI (Render). In dev, use Vite proxy: leave empty and use /api prefix. */
export function apiBase(): string {
  const env = import.meta.env.VITE_API_URL?.trim();
  if (!env) return "";
  let base = env.replace(/\/$/, "");
  // Accept "api.onrender.com" without scheme (common misconfig)
  if (base && !/^https?:\/\//i.test(base)) {
    base = `https://${base}`;
  }
  return base;
}

/** When no VITE_API_URL, dev server proxies /api → backend */
export function apiUrl(path: string): string {
  const base = apiBase();
  if (base) return `${base}${path.startsWith("/") ? path : `/${path}`}`;
  return `/api${path.startsWith("/") ? path : `/${path}`}`;
}

export async function apiGet<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const pathResolved = apiUrl(path);
  const u = pathResolved.startsWith("http")
    ? new URL(pathResolved)
    : new URL(pathResolved, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "") u.searchParams.set(k, String(v));
    }
  }
  const r = await fetch(u.toString());
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: object): Promise<T> {
  const url = apiUrl(path);
  const target = url.startsWith("http") ? url : new URL(url, window.location.origin).toString();
  const r = await fetch(target, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}
