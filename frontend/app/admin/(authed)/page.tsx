import { cookies } from "next/headers";

import { api } from "@/lib/api";

async function gather() {
  const cookieHeader = (() => {
    const s = cookies().get("admin_session");
    return s ? `admin_session=${s.value}` : undefined;
  })();
  const [channels, summaries, logs] = await Promise.all([
    api.admin.channels(cookieHeader).catch(() => []),
    api.admin.summaries(cookieHeader, 1).catch(() => []),
    api.admin.logs(cookieHeader, "error", 20).catch(() => []),
  ]);
  return { channels, summaries, logs };
}

export default async function AdminDashboard() {
  const { channels, summaries, logs } = await gather();
  const active = channels.filter((c) => c.active);
  const stale = active.filter((c) => !c.last_success_at);
  const lastSummary = summaries[0];

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      <Card title="活跃渠道">
        <p className="text-3xl font-semibold">{active.length}</p>
        <p className="mt-1 text-xs text-neutral-500">/ {channels.length} 总数</p>
      </Card>
      <Card title="未抓取过">
        <p className="text-3xl font-semibold">{stale.length}</p>
        <p className="mt-1 text-xs text-neutral-500">尚未有过成功记录</p>
      </Card>
      <Card title="近 20 条错误日志">
        <p className="text-3xl font-semibold">{logs.length}</p>
        <p className="mt-1 text-xs text-neutral-500">
          <a className="text-blue-600 underline" href="/admin/logs?level=error">
            查看
          </a>
        </p>
      </Card>

      <div className="md:col-span-3">
        <Card title="最新 AI 摘要">
          {lastSummary ? (
            <>
              <p className="text-sm text-neutral-800">{lastSummary.summary_zh}</p>
              <p className="mt-2 text-xs text-neutral-500">
                {lastSummary.model_used} ·{" "}
                {new Date(lastSummary.generated_at).toLocaleString("zh-CN")}
              </p>
            </>
          ) : (
            <p className="text-sm text-neutral-500">
              还没有摘要。先到{" "}
              <a className="text-blue-600 underline" href="/admin/ai">
                /admin/ai
              </a>{" "}
              配置 LLM 端点并生成。
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4">
      <h2 className="text-xs uppercase tracking-wide text-neutral-500">{title}</h2>
      <div className="mt-2">{children}</div>
    </div>
  );
}
