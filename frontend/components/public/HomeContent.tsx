"use client";

import { useMemo, useState } from "react";

import AmountInput from "@/components/public/AmountInput";
import ChannelTable from "@/components/public/ChannelTable";
import HistoryChart from "@/components/public/HistoryChart";
import type { LatestRate } from "@/lib/api";

type Props = {
  initialRates: LatestRate[];
};

export default function HomeContent({ initialRates }: Props) {
  const [amount, setAmount] = useState<number>(1000);

  const chartChannels = useMemo(
    () => initialRates.map((r) => ({ code: r.channel_code, name_zh: r.channel_name_zh })),
    [initialRates],
  );

  return (
    <div className="space-y-6">
      <div>
        <AmountInput onChangeDebounced={setAmount} />
      </div>
      <ChannelTable rows={initialRates} amountCny={amount} />
      {chartChannels.length > 0 && <HistoryChart channels={chartChannels} />}
    </div>
  );
}
