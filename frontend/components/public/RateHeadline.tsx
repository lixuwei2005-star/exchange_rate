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
    <div className="text-center">
      <div className="text-sm text-neutral-500">{zhCN.midmarketLabel}</div>
      <div className="mt-2 text-4xl font-bold tracking-tight md:text-5xl">
        {zhCN.heroPrefix} <span className="tabular-nums">{display}</span> {zhCN.heroSuffix}
      </div>
    </div>
  );
}
