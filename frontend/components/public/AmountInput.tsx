"use client";

import { useEffect, useRef, useState } from "react";

import { zhCN } from "@/lib/i18n/zh-CN";

const STORAGE_KEY = "rate.amount.cny";
const DEFAULT_AMOUNT = 1000;

type Props = {
  onChangeDebounced: (n: number) => void;
};

export default function AmountInput({ onChangeDebounced }: Props) {
  const [raw, setRaw] = useState<string>(String(DEFAULT_AMOUNT));
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Restore from localStorage on mount, then commit once so parent sees the
  // initial value (after restoration) without waiting for user input.
  useEffect(() => {
    const stored = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    const initial = stored ? Number(stored) : DEFAULT_AMOUNT;
    const safe = Number.isFinite(initial) && initial > 0 ? initial : DEFAULT_AMOUNT;
    setRaw(String(safe));
    onChangeDebounced(safe);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function commit(next: string) {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      const n = parseFloat(next.replace(/,/g, ""));
      if (Number.isFinite(n) && n > 0) {
        localStorage.setItem(STORAGE_KEY, String(n));
        onChangeDebounced(n);
      }
    }, 300);
  }

  return (
    <div className="flex items-center justify-center gap-2 text-base md:text-lg">
      <span>{zhCN.amountLabel}</span>
      <input
        type="number"
        inputMode="decimal"
        min={1}
        value={raw}
        onChange={(e) => {
          setRaw(e.target.value);
          commit(e.target.value);
        }}
        className="w-32 rounded border border-neutral-300 px-3 py-2 text-right tabular-nums"
      />
      <span>{zhCN.amountUnit}</span>
      <span className="text-neutral-500">{zhCN.amountSuffix}</span>
    </div>
  );
}
