"use client";

import { useEffect, useMemo, useState } from "react";

import { api, type LatestRate, type WiseQuoteResponse } from "@/lib/api";
import { displayCnyPerMyr, feeDisplay, grossCnyToMyr, relativeTimeZh } from "@/lib/format";
import { zhCN } from "@/lib/i18n/zh-CN";

type SortKey = "receive" | "channel" | "updated";

type Props = {
  rows: LatestRate[];
  amountCny: number;
};

const NUMBER_FMT = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 0,
});

export default function ChannelTable({ rows, amountCny }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("receive");
  const [desc, setDesc] = useState(true);
  // Wise's fee has a sizable fixed component (≈19 CNY base + ~0.6% variable),
  // so a static snapshot value is wrong for amounts != 1000. Re-quote against
  // the live Wise endpoint whenever the user's amount changes.
  const [wiseQuote, setWiseQuote] = useState<WiseQuoteResponse | null>(null);
  const [wiseFor, setWiseFor] = useState<number | null>(null); // the amount the cached quote was for

  useEffect(() => {
    // Only re-quote if the homepage rows include an active Wise row.
    const hasWise = rows.some((r) => r.channel_code === "wise" && !r.is_stale);
    if (!hasWise || amountCny <= 0) return;
    let cancelled = false;
    api
      .quoteWise(amountCny)
      .then((q) => {
        if (!cancelled) {
          setWiseQuote(q);
          setWiseFor(amountCny);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setWiseQuote(null);
          setWiseFor(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [amountCny, rows]);

  const enriched = useMemo(() => {
    return rows.map((r) => {
      // '你能拿到' is the pure rate * amount (no fee subtraction).
      // For Wise, prefer the freshly-quoted target_amount when we have one
      // for the current amount — it's already net-of-fee at exactly that
      // input, more accurate than amount * stored_effective_rate.
      let myr: number | null = null;
      if (!r.is_stale) {
        if (r.channel_code === "wise" && wiseQuote && wiseFor === amountCny) {
          myr = parseFloat(wiseQuote.target_amount);
        } else {
          myr = grossCnyToMyr(amountCny, r.rate);
        }
      }
      return { ...r, myr };
    });
  }, [rows, amountCny, wiseQuote, wiseFor]);

  const sorted = useMemo(() => {
    const arr = [...enriched];
    arr.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "receive") {
        cmp = (a.myr ?? -1) - (b.myr ?? -1);
      } else if (sortKey === "channel") {
        cmp = a.channel_name_zh.localeCompare(b.channel_name_zh, "zh");
      } else {
        cmp = new Date(a.fetched_at).getTime() - new Date(b.fetched_at).getTime();
      }
      return desc ? -cmp : cmp;
    });
    return arr;
  }, [enriched, sortKey, desc]);

  function onSort(k: SortKey) {
    if (k === sortKey) setDesc((d) => !d);
    else {
      setSortKey(k);
      setDesc(true);
    }
  }

  /** Fee for one row, with the live Wise quote applied when available. */
  function feeFor(r: LatestRate): string {
    if (r.channel_code === "wise" && wiseQuote && wiseFor === amountCny) {
      const f = parseFloat(wiseQuote.fee);
      if (Number.isFinite(f) && f > 0) {
        return `${NUMBER_FMT.format(f)} ${wiseQuote.fee_currency}`;
      }
    }
    return feeDisplay(r);
  }

  return (
    <div className="overflow-x-auto rounded-2xl border border-neutral-200 bg-white shadow-sm">
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase tracking-wider text-neutral-400">
          <tr>
            <Th onClick={() => onSort("channel")} active={sortKey === "channel"} desc={desc}>
              {zhCN.tableHeaderChannel}
            </Th>
            <th className="px-4 py-2.5 text-right font-medium">{zhCN.tableHeaderRate}</th>
            <Th
              onClick={() => onSort("receive")}
              active={sortKey === "receive"}
              desc={desc}
              align="right"
            >
              {zhCN.tableHeaderReceive}
            </Th>
            <th className="px-4 py-2.5 text-right font-medium">{zhCN.tableHeaderFee}</th>
            <Th
              onClick={() => onSort("updated")}
              active={sortKey === "updated"}
              desc={desc}
              align="right"
            >
              {zhCN.tableHeaderUpdated}
            </Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr
              key={r.channel_code}
              className={`border-t border-neutral-100 ${r.is_stale ? "text-neutral-400" : ""}`}
            >
              <td className="px-4 py-3">{r.channel_name_zh}</td>
              <td className="px-4 py-3 text-right tabular-nums">{displayCnyPerMyr(r.rate)}</td>
              <td className="px-4 py-3 text-right font-medium tabular-nums">
                {r.is_stale ? zhCN.unavailable : r.myr?.toFixed(2)}
              </td>
              <td className="px-4 py-3 text-right text-neutral-600">{feeFor(r)}</td>
              <td className="px-4 py-3 text-right text-xs text-neutral-400">
                {r.is_stale ? zhCN.unavailable : relativeTimeZh(r.fetched_at)}
              </td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={5} className="px-3 py-6 text-center text-neutral-500">
                {zhCN.unavailable}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Th({
  children,
  onClick,
  active,
  desc,
  align = "left",
}: {
  children: React.ReactNode;
  onClick: () => void;
  active: boolean;
  desc: boolean;
  align?: "left" | "right";
}) {
  return (
    <th className={`px-4 py-2.5 font-medium ${align === "right" ? "text-right" : "text-left"}`}>
      <button
        type="button"
        onClick={onClick}
        className={`inline-flex items-center gap-1 hover:text-neutral-700 ${
          active ? "text-neutral-700" : ""
        }`}
      >
        {children}
        {active && <span aria-hidden>{desc ? "▼" : "▲"}</span>}
      </button>
    </th>
  );
}
