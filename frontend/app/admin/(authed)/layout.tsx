import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { apiFetch, HttpError } from "@/lib/api";

/**
 * Server Component auth gate for everything inside the `(authed)` route
 * group. /admin/login lives OUTSIDE this group so it never recursively
 * triggers this check.
 *
 * Server Components don't carry the browser's cookies automatically — they
 * must be read via `next/headers` and forwarded as an explicit Cookie header.
 */
async function verifySession(): Promise<{ username: string } | null> {
  const jar = cookies();
  const session = jar.get("admin_session");
  if (!session) return null;
  try {
    return await apiFetch<{ username: string }>("/api/admin/me", {
      cookieHeader: `admin_session=${session.value}`,
      cache: "no-store",
    });
  } catch (e) {
    if (e instanceof HttpError && e.status === 401) return null;
    throw e;
  }
}

export default async function AuthedAdminLayout({ children }: { children: ReactNode }) {
  const me = await verifySession();
  if (!me) redirect("/admin/login");
  return <div className="min-h-screen bg-neutral-50">{children}</div>;
}
