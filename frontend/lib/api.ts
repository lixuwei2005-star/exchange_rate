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
const CLIENT_BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

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

export const api = {
  health: () => apiFetch<HealthResponse>("/api/health"),
};
