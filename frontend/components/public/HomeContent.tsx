"use client";

import { useState } from "react";

import AmountInput from "@/components/public/AmountInput";
import ChannelTable from "@/components/public/ChannelTable";
import HistoryChart from "@/components/public/HistoryChart";
import type { LatestRate } from "@/lib/api";

type Props = {
  initialRates: LatestRate[];
};

export default function HomeContent({ initialRates }: Props) {
  const [amount, setAmount] = useState<number>(1000);

  return (
    <div className="space-y-6">
      <div>
        <AmountInput onChangeDebounced={setAmount} />
      </div>
      <ChannelTable rows={initialRates} amountCny={amount} />
      {/* Single-source trend chart (UnionPay International) — see HistoryChart. */}
      <HistoryChart />
    </div>
  );
}
