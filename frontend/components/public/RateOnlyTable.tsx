import type { LatestRate } from "@/lib/api";
import { displayCnyPerMyr, relativeTimeZh } from "@/lib/format";
import { zhCN } from "@/lib/i18n/zh-CN";

import ChannelLogo from "./ChannelLogo";

/**
 * Pure-rate comparison: each channel's advertised pre-fee rate, sorted
 * with the best (lowest CNY per MYR) on top. Wise's row uses its mid-market
 * headline (extracted from raw_payload by the backend), so users can see at
 * a glance which channels mark up the headline rate vs. charge a separate
 * transparent fee.
 *
 * Server Component — no client-side state, no event handlers.
 */
export default function RateOnlyTable({ rows }: { rows: LatestRate[] }) {
  if (rows.length === 0) return null;

  // Keep stale channels visible (shown as "暂时不可用") instead of dropping
  // them — a channel vanishing reads worse than one honestly marked stale.
  const midmarketRank: Record<string, number> = {
    midmarket: 1,
    midmarket2: 2,
    midmarket3: 3,
  };
  // Sort: fresh rows first (best rate on top), then stale rows at the bottom.
  // The three mid-market references are pinned among the fresh group in a
  // fixed 1→2→3 order. headline_rate is MYR/CNY: higher = better; displayed as
  // `1 MYR = X CNY` (X = 1/rate), so MYR/CNY descending == displayed ascending.
  const sorted = [...rows].sort((a, b) => {
    if (a.is_stale !== b.is_stale) return a.is_stale ? 1 : -1;
    const ra = midmarketRank[a.channel_code] ?? 0;
    const rb = midmarketRank[b.channel_code] ?? 0;
    if (ra || rb) return ra - rb;
    return parseFloat(b.headline_rate) - parseFloat(a.headline_rate);
  });

  return (
    <section className="overflow-hidden rounded-2xl border border-neutral-200 bg-white shadow-sm">
      <header className="border-b border-neutral-100 px-4 py-3">
        <h2 className="text-sm font-semibold tracking-tight">{zhCN.rateOnlyTitle}</h2>
        <p className="mt-1 text-xs leading-relaxed text-neutral-500">{zhCN.rateOnlyHint}</p>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wider text-neutral-400">
            <tr>
              <th className="px-2.5 py-2.5 font-medium sm:px-4">{zhCN.tableHeaderChannel}</th>
              <th className="px-2.5 py-2.5 text-right font-medium sm:px-4">
                {zhCN.tableHeaderRate}
              </th>
              <th className="whitespace-nowrap px-2.5 py-2.5 text-right font-medium sm:px-4">
                {zhCN.tableHeaderUpdated}
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => (
              <tr
                key={r.channel_code}
                className={`border-t border-neutral-100 ${r.is_stale ? "text-neutral-400" : ""}`}
              >
                <td className="px-2.5 py-3 sm:px-4">
                  {/* Mobile: name on its own line, logo stacked beneath so a long
                      Chinese name never gets squeezed into vertical characters.
                      Desktop (sm+): name with the logo to its right. */}
                  <span className="flex flex-col items-start gap-1 sm:flex-row sm:items-center sm:gap-2.5">
                    <span className="whitespace-nowrap">{r.channel_name_zh}</span>
                    <ChannelLogo code={r.channel_code} />
                  </span>
                </td>
                <td className="px-2.5 py-3 text-right font-medium tabular-nums sm:px-4">
                  {r.is_stale ? zhCN.unavailable : displayCnyPerMyr(r.headline_rate)}
                </td>
                <td className="whitespace-nowrap px-2.5 py-3 text-right text-xs text-neutral-400 sm:px-4">
                  {/* "更新于" reflects when the rate VALUE last changed, not the
                      last poll — an unchanged rate keeps its original time. */}
                  {r.is_stale
                    ? "—"
                    : `${zhCN.updatedAtPrefix} ${relativeTimeZh(r.rate_changed_at)}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
