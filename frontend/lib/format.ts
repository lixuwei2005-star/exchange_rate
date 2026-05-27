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

/** Apply fee & convert N CNY → MYR using stored MYR/CNY rate. */
export function convertCnyToMyr(
  cnyAmount: number,
  myrPerCny: string | number,
  fee: { kind: "flat-cny"; amount: number } | { kind: "flat-myr"; amount: number } | { kind: "none" },
): number {
  const r = typeof myrPerCny === "string" ? parseFloat(myrPerCny) : myrPerCny;
  if (!Number.isFinite(r) || r <= 0 || cnyAmount <= 0) return 0;
  let cnyAfterFee = cnyAmount;
  let myrFee = 0;
  if (fee.kind === "flat-cny") cnyAfterFee = Math.max(0, cnyAmount - fee.amount);
  else if (fee.kind === "flat-myr") myrFee = fee.amount;
  const gross = cnyAfterFee * r;
  return Math.max(0, gross - myrFee);
}

/** Human-friendly fee label per channel. Constants tracked in CLAUDE.md §6. */
export function feeLabel(channel: string): string {
  switch (channel) {
    case "boc":
      return zhCN.feeBOC;
    case "maybank":
      return zhCN.feeMaybank;
    case "cimb":
      return zhCN.feeCIMB;
    case "visa":
    case "mastercard":
      return zhCN.feeNetworkMarkup;
    case "wise":
      return zhCN.feeWise;
    default:
      return zhCN.feeNone;
  }
}

/** What kind of fee deduction to apply for a given channel. */
export function feeForChannel(channel: string): Parameters<typeof convertCnyToMyr>[2] {
  switch (channel) {
    case "boc":
      return { kind: "flat-cny", amount: 50 };
    case "maybank":
    case "cimb":
      return { kind: "flat-myr", amount: 10 };
    default:
      // Visa/MC markup is already baked into the stored rate.
      // UnionPay/Wise/midmarket: no separate flat fee modeled.
      return { kind: "none" };
  }
}
