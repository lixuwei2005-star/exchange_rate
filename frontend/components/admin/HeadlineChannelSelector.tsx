"use client";

import { useState } from "react";

import { type AdminChannel, api, HttpError } from "@/lib/api";

const SETTING_KEY = "display.headline_channel";

/**
 * Picks which channel's rate the public homepage hero ("1 MYR = X CNY") shows.
 * Saves to the `display.headline_channel` setting on change. Only active
 * channels are offered — the hero needs a channel that actually has data, and
 * the backend rejects inactive/unknown codes.
 */
export default function HeadlineChannelSelector({
  channels,
  current,
}: {
  channels: AdminChannel[];
  current: string;
}) {
  const active = channels.filter((c) => c.active);
  const [value, setValue] = useState(current);
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  async function onChange(next: string) {
    const prev = value;
    setValue(next);
    setStatus("saving");
    setError(null);
    try {
      await api.admin.putSetting(SETTING_KEY, next);
      setStatus("saved");
    } catch (e) {
      setValue(prev); // revert on failure
      setStatus("error");
      setError(e instanceof HttpError ? e.detail : "保存失败");
    }
  }

  return (
    <div className="mb-6 rounded-lg border border-neutral-200 bg-white p-4">
      <h2 className="text-sm font-semibold">首页大数字汇率来源</h2>
      <p className="mt-1 text-xs text-neutral-500">
        顶部「1 MYR = X CNY」大方框显示哪个渠道的汇率。只能选已启用的渠道。
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="rounded border border-neutral-300 px-3 py-1.5 text-sm"
        >
          {active.map((c) => (
            <option key={c.code} value={c.code}>
              {c.name_zh}（{c.code}）
            </option>
          ))}
          {/* Keep the current value selectable even if it's somehow not in the
              active list, so the dropdown isn't silently wrong. */}
          {!active.some((c) => c.code === value) && (
            <option value={value}>{value}（当前，未启用）</option>
          )}
        </select>
        {status === "saving" && <span className="text-xs text-neutral-400">保存中…</span>}
        {status === "saved" && <span className="text-xs text-green-600">已保存</span>}
        {status === "error" && <span className="text-xs text-red-600">{error}</span>}
      </div>
    </div>
  );
}
