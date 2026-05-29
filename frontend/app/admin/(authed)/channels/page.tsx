import { cookies } from "next/headers";

import ChannelsTable from "@/components/admin/ChannelsTable";
import HeadlineChannelSelector from "@/components/admin/HeadlineChannelSelector";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ChannelsPage() {
  const cookieHeader = (() => {
    const s = cookies().get("admin_session");
    return s ? `admin_session=${s.value}` : undefined;
  })();
  const [channels, settings] = await Promise.all([
    api.admin.channels(cookieHeader).catch(() => []),
    api.admin.settings(cookieHeader).catch(() => []),
  ]);
  const headlineChannel =
    settings.find((s) => s.key === "display.headline_channel")?.value ?? "midmarket";
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">渠道管理</h1>
      <HeadlineChannelSelector channels={channels} current={headlineChannel} />
      <ChannelsTable initial={channels} />
    </div>
  );
}
