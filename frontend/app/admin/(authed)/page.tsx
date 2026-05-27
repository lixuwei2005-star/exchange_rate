import { cookies } from "next/headers";

import LogoutButton from "@/components/admin/LogoutButton";
import { apiFetch } from "@/lib/api";
import { zhCN } from "@/lib/i18n/zh-CN";

async function getMe(): Promise<{ username: string }> {
  const session = cookies().get("admin_session");
  return apiFetch<{ username: string }>("/api/admin/me", {
    cookieHeader: session ? `admin_session=${session.value}` : undefined,
    cache: "no-store",
  });
}

export default async function AdminDashboard() {
  const me = await getMe();
  return (
    <div className="mx-auto max-w-4xl p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{zhCN.adminDashboardTitle}</h1>
        <LogoutButton />
      </div>
      <p className="mt-4 text-neutral-700">Hello, {me.username}</p>
      <p className="mt-2 text-sm text-neutral-500">
        Channels / AI / Logs 页面会在后续 phase 接入真实数据。
      </p>
      <nav className="mt-6 flex gap-4 text-sm">
        <a className="text-blue-600 underline" href="/admin/channels">
          /admin/channels
        </a>
        <a className="text-blue-600 underline" href="/admin/ai">
          /admin/ai
        </a>
        <a className="text-blue-600 underline" href="/admin/logs">
          /admin/logs
        </a>
      </nav>
    </div>
  );
}
