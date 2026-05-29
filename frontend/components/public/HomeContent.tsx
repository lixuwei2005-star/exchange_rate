"use client";

import { useState } from "react";

import AmountInput from "@/components/public/AmountInput";
import ChannelTable from "@/components/public/ChannelTable";
import HistoryChart from "@/components/public/HistoryChart";
import IntradayChart from "@/components/public/IntradayChart";
import type { LatestRate } from "@/lib/api";
import { zhCN } from "@/lib/i18n/zh-CN";

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
      {/* Intraday (Wise, 24h/72h toggle) sits above the daily/yearly charts. */}
      <IntradayChart />
      {/* Daily + yearly trend charts (UnionPay International) — see HistoryChart. */}
      <HistoryChart days={30} title={zhCN.chartTitle} />
      <HistoryChart days={365} title={zhCN.chartTitleYear} />
    </div>
  );
}
