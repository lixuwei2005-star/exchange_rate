/**
 * Typed fetch wrapper for talking to the FastAPI backend.
 *
 * Two base URLs:
 *  - BACKEND_URL_INTERNAL  — used by Server Components fetching from inside
 *                            the docker network (e.g. http://backend:8000).
 *                            They must explicitly forward the user's cookie
 *                            via `headers: { cookie: ... }` since they don't
 *                            run in the browser.
 *  - NEXT_PUBLIC_BACKEND_URL — used by Client Components running in the
 *                              browser. Must be a URL the browser resolves.
 *                              Client fetches MUST set `credentials: 'include'`
 *                              so the admin cookie is sent.
 *
 * In prod behind Nginx both collapse to the same public origin.
 */

const SERVER_BASE = process.env.BACKEND_URL_INTERNAL ?? "http://backend:8000";
// NEXT_PUBLIC_* is statically inlined at build time. If unset, default to
// relative URLs — correct for same-origin prod deployments behind a reverse
// proxy. Dev sets the explicit cross-port URL via .env.
const CLIENT_BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? "";

function isServer(): boolean {
  return typeof window === "undefined";
}

function baseUrl(): string {
  return isServer() ? SERVER_BASE : CLIENT_BASE;
}

export type ApiError = {
  status: number;
  detail: string;
};

export class HttpError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`HTTP ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

type FetchOptions = RequestInit & {
  /** Server-side cookie forwarding (Server Components / RSC). */
  cookieHeader?: string;
};

export async function apiFetch<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { cookieHeader, headers, ...rest } = options;
  const finalHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...((headers as Record<string, string>) ?? {}),
  };
  if (cookieHeader) finalHeaders["Cookie"] = cookieHeader;

  const init: RequestInit = {
    ...rest,
    headers: finalHeaders,
  };
  // Browser side: always include cookies so the admin session is carried.
  if (!isServer()) {
    init.credentials = "include";
  }

  const res = await fetch(`${baseUrl()}${path}`, init);
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : String(body);
    throw new HttpError(res.status, detail);
  }
  return body as T;
}

// ----- Public endpoints -----

export type HealthResponse = {
  ok: boolean;
  channels: Record<string, "fresh" | "stale" | "disabled">;
};

export type LatestRate = {
  channel_code: string;
  channel_name_zh: string;
  // Effective rate (already includes any baked-in fee/markup) — used for
  // the '你能拿到' computation in the detailed table.
  rate: string; // decimal as string
  // Pre-fee advertised rate — used for the pure-rate comparison table.
  // For most channels equals `rate`; for Wise it's the mid-market headline.
  headline_rate: string;
  rate_type: string;
  // Absolute fee at the channel's reference quote. Static fallback only —
  // for Wise the homepage queries /api/quote/wise with the user's actual
  // amount to get an accurate fee (Wise's fee has a sizable fixed part).
  fee_estimate: string | null;
  fee_currency: string | null;
  fetched_at: string; // ISO
  is_stale: boolean;
};

export type HistoryPoint = {
  date: string;
  rate: string;
};

export type SummaryResponse = {
  summary_zh: string | null;
  generated_at: string | null;
  model_used: string | null;
};

export type ChannelScheduleKind = "interval" | "daily";

export type AdminChannel = {
  code: string;
  name_en: string;
  name_zh: string;
  source_url: string | null;
  active: boolean;
  last_success_at: string | null;
  last_error_at: string | null;
  last_error_msg: string | null;
  // Per-channel refresh policy. `daily_time_cn` is HH:MM in Asia/Shanghai
  // (UTC+8). When schedule_kind='interval', interval_minutes is used.
  schedule_kind: ChannelScheduleKind;
  interval_minutes: number | null;
  daily_time_cn: string | null;
};

export type ChannelPatchBody = Partial<
  Pick<
    AdminChannel,
    | "active"
    | "name_en"
    | "name_zh"
    | "source_url"
    | "schedule_kind"
    | "interval_minutes"
    | "daily_time_cn"
  >
>;

export type AdminSetting = {
  key: string;
  value: string; // "***" when is_encrypted
  is_encrypted: boolean;
  updated_at: string;
};

export type AdminSummary = {
  id: number;
  base_currency: string;
  quote_currency: string;
  summary_zh: string;
  model_used: string;
  generated_at: string;
};

export type AdminLog = {
  id: number;
  channel_code: string | null;
  level: "info" | "warn" | "error" | string;
  message: string;
  created_at: string;
};

export type AITestResult = {
  ok: boolean;
  latency_ms: number | null;
  model_used: string | null;
  error: string | null;
};

export const api = {
  health: () => apiFetch<HealthResponse>("/api/health"),
  ratesLatest: (base = "CNY", quote = "MYR") =>
    apiFetch<LatestRate[]>(`/api/rates/latest?base=${base}&quote=${quote}`),
  ratesHistory: (channel: string, days = 30, base = "CNY", quote = "MYR") =>
    apiFetch<HistoryPoint[]>(
      `/api/rates/history?channel=${channel}&days=${days}&base=${base}&quote=${quote}`,
    ),
  summary: (base = "CNY", quote = "MYR") =>
    apiFetch<SummaryResponse>(`/api/summary?base=${base}&quote=${quote}`),

  admin: {
    me: (cookieHeader?: string) =>
      apiFetch<{ username: string }>("/api/admin/me", { cookieHeader, cache: "no-store" }),
    channels: (cookieHeader?: string) =>
      apiFetch<AdminChannel[]>("/api/admin/channels", { cookieHeader, cache: "no-store" }),
    patchChannel: (code: string, body: ChannelPatchBody) =>
      apiFetch<AdminChannel>(`/api/admin/channels/${code}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    scrapeNow: (code: string) =>
      apiFetch<{ ok: boolean; channel: string; rate: string; fetched_at: string }>(
        `/api/admin/channels/${code}/scrape-now`,
        { method: "POST" },
      ),
    settings: (cookieHeader?: string) =>
      apiFetch<AdminSetting[]>("/api/admin/settings", { cookieHeader, cache: "no-store" }),
    putSetting: (key: string, value: string) =>
      apiFetch<AdminSetting>(`/api/admin/settings/${encodeURIComponent(key)}`, {
        method: "PUT",
        body: JSON.stringify({ value }),
      }),
    aiTest: () => apiFetch<AITestResult>("/api/admin/ai/test", { method: "POST" }),
    summaries: (cookieHeader?: string, limit = 20) =>
      apiFetch<AdminSummary[]>(`/api/admin/summaries?limit=${limit}`, {
        cookieHeader,
        cache: "no-store",
      }),
    regenerateSummary: () =>
      apiFetch<{ ok: boolean; summary: string; model_used: string; generated_at: string }>(
        "/api/admin/summaries/regenerate",
        { method: "POST" },
      ),
    logs: (cookieHeader?: string, level?: string, limit = 200) =>
      apiFetch<AdminLog[]>(`/api/admin/logs?limit=${limit}${level ? `&level=${level}` : ""}`, {
        cookieHeader,
        cache: "no-store",
      }),
  },
};
