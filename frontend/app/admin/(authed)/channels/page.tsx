import { cookies } from "next/headers";

import ChannelsTable from "@/components/admin/ChannelsTable";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ChannelsPage() {
  const cookieHeader = (() => {
    const s = cookies().get("admin_session");
    return s ? `admin_session=${s.value}` : undefined;
  })();
  const channels = await api.admin.channels(cookieHeader).catch(() => []);
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">渠道管理</h1>
      <ChannelsTable initial={channels} />
    </div>
  );
}
