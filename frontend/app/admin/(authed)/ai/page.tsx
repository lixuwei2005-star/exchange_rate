import { cookies } from "next/headers";

import AISettingsForm from "@/components/admin/AISettingsForm";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AIPage() {
  const cookieHeader = (() => {
    const s = cookies().get("admin_session");
    return s ? `admin_session=${s.value}` : undefined;
  })();
  const [settings, summaries] = await Promise.all([
    api.admin.settings(cookieHeader).catch(() => []),
    api.admin.summaries(cookieHeader, 5).catch(() => []),
  ]);
  const ai = settings.filter((s) => s.key.startsWith("ai."));
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">AI 设置</h1>
      <AISettingsForm initial={ai} summaries={summaries} />
    </div>
  );
}
