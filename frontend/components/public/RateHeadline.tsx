"use client";

import { useId, useState } from "react";

import { displayCnyPerMyr } from "@/lib/format";
import { zhCN } from "@/lib/i18n/zh-CN";

type Props = {
  /** Midmarket rate as MYR per 1 CNY, decimal string. May be null if no data. */
  myrPerCny: string | null;
};

export default function RateHeadline({ myrPerCny }: Props) {
  const tipId = useId();
  const [show, setShow] = useState(false);
  const display = myrPerCny ? displayCnyPerMyr(myrPerCny) : "—";
  return (
    <div className="text-center">
      <div className="text-sm text-neutral-500">{zhCN.midmarketLabel}</div>
      <div className="mt-2 text-4xl font-bold tracking-tight md:text-5xl">
        {zhCN.heroPrefix} <span className="tabular-nums">{display}</span> {zhCN.heroSuffix}
      </div>
      <div className="relative mt-2 inline-block">
        <button
          type="button"
          aria-describedby={tipId}
          onMouseEnter={() => setShow(true)}
          onMouseLeave={() => setShow(false)}
          onFocus={() => setShow(true)}
          onBlur={() => setShow(false)}
          onClick={() => setShow((s) => !s)}
          className="text-xs text-neutral-400 underline decoration-dotted underline-offset-2"
        >
          {zhCN.heroTooltip}
        </button>
        {show && (
          <div
            role="tooltip"
            id={tipId}
            className="absolute left-1/2 z-10 mt-2 w-64 -translate-x-1/2 rounded border border-neutral-200 bg-white p-2 text-xs text-neutral-700 shadow"
          >
            {zhCN.heroTooltip}
          </div>
        )}
      </div>
    </div>
  );
}
