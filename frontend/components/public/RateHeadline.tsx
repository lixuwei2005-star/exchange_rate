"use client";

import { displayCnyPerMyr } from "@/lib/format";
import { zhCN } from "@/lib/i18n/zh-CN";

type Props = {
  /** Midmarket rate as MYR per 1 CNY, decimal string. May be null if no data. */
  myrPerCny: string | null;
};

export default function RateHeadline({ myrPerCny }: Props) {
  const display = myrPerCny ? displayCnyPerMyr(myrPerCny) : "—";
  return (
    <div className="rounded-2xl border border-neutral-200 bg-white px-6 py-8 text-center shadow-sm md:py-12">
      <div className="text-xs uppercase tracking-widest text-neutral-400">
        {zhCN.midmarketLabel}
      </div>
      <div className="mt-3 text-3xl font-semibold tracking-tight md:text-5xl">
        <span className="text-neutral-500">{zhCN.heroPrefix}</span>{" "}
        <span className="tabular-nums">{display}</span>{" "}
        <span className="text-neutral-500">{zhCN.heroSuffix}</span>
      </div>
    </div>
  );
}
