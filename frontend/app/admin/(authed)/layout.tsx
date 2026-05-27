import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import AdminNav from "@/components/admin/AdminNav";
import { apiFetch, HttpError } from "@/lib/api";

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
  return (
    <div className="min-h-screen bg-neutral-50">
      <AdminNav username={me.username} />
      <div className="mx-auto max-w-5xl px-4 py-6">{children}</div>
    </div>
  );
}
