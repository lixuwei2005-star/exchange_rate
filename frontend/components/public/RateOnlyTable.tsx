import type { LatestRate } from "@/lib/api";
import { displayCnyPerMyr } from "@/lib/format";
import { zhCN } from "@/lib/i18n/zh-CN";

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
  const active = rows.filter((r) => !r.is_stale && parseFloat(r.headline_rate) > 0);
  if (active.length === 0) return null;

  // headline_rate is MYR/CNY. Higher MYR/CNY = better for the customer
  // exchanging CNY → MYR. Displayed as `1 MYR = X CNY`, where X = 1/rate;
  // sorting by displayed CNY/MYR ascending == sorting by MYR/CNY descending.
  const sorted = [...active].sort(
    (a, b) => parseFloat(b.headline_rate) - parseFloat(a.headline_rate),
  );

  return (
    <section className="rounded-lg border border-neutral-200 bg-white">
      <header className="border-b border-neutral-100 px-3 py-2">
        <h2 className="text-sm font-semibold">{zhCN.rateOnlyTitle}</h2>
        <p className="mt-0.5 text-xs leading-relaxed text-neutral-500">{zhCN.rateOnlyHint}</p>
      </header>
      <table className="w-full text-sm">
        <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500">
          <tr>
            <th className="px-3 py-2">{zhCN.tableHeaderChannel}</th>
            <th className="px-3 py-2 text-right">{zhCN.tableHeaderRate}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.channel_code} className="border-t border-neutral-100">
              <td className="px-3 py-2">{r.channel_name_zh}</td>
              <td className="px-3 py-2 text-right tabular-nums">
                {displayCnyPerMyr(r.headline_rate)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
