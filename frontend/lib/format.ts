import { zhCN } from "@/lib/i18n/zh-CN";

/** "5 分钟前" / "2 小时前" / "1 天前" — Chinese relative time. */
export function relativeTimeZh(iso: string, now: Date = new Date()): string {
  const t = new Date(iso).getTime();
  const diffSec = Math.max(0, Math.round((now.getTime() - t) / 1000));
  if (diffSec < 60) return zhCN.justNow;
  const m = Math.round(diffSec / 60);
  if (m < 60) return `${m} ${zhCN.minutesAgo}`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} ${zhCN.hoursAgo}`;
  const d = Math.round(h / 24);
  return `${d} ${zhCN.daysAgo}`;
}

/** Stored rate is MYR per 1 CNY. Display 1 MYR = X CNY  ⇒ 1 / rate. */
export function displayCnyPerMyr(myrPerCny: string | number): string {
  const n = typeof myrPerCny === "string" ? parseFloat(myrPerCny) : myrPerCny;
  if (!Number.isFinite(n) || n <= 0) return "—";
  return (1 / n).toFixed(4);
}

/** Pure conversion: amount × stored MYR-per-CNY rate. No fee deducted —
 * fees aren't modeled in the homepage table; users check each channel
 * directly for the exact fee they'd be charged. */
export function grossCnyToMyr(cnyAmount: number, myrPerCny: string | number): number {
  const r = typeof myrPerCny === "string" ? parseFloat(myrPerCny) : myrPerCny;
  if (!Number.isFinite(r) || r <= 0 || cnyAmount <= 0) return 0;
  return cnyAmount * r;
}
