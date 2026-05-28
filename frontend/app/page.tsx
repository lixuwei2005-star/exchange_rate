import HomeContent from "@/components/public/HomeContent";
import RateHeadline from "@/components/public/RateHeadline";
import RateOnlyTable from "@/components/public/RateOnlyTable";
import SiteTitle from "@/components/public/SiteTitle";
import { api, type LatestRate, type SummaryResponse } from "@/lib/api";
import { relativeTimeZh } from "@/lib/format";
import { zhCN } from "@/lib/i18n/zh-CN";

// ISR: re-render at most once a minute. Backend scrapers run every 30 min
// (midmarket/wise) up to 6 h (maybank/cimb), so a 60s ceiling keeps the
// homepage close to the freshest snapshot without spamming re-renders.
export const revalidate = 60;

async function safeFetch<T>(promise: Promise<T>, fallback: T): Promise<T> {
  try {
    return await promise;
  } catch {
    return fallback;
  }
}

export default async function HomePage() {
  const [rates, summary] = await Promise.all([
    safeFetch<LatestRate[]>(api.ratesLatest("CNY", "MYR"), []),
    safeFetch<SummaryResponse>(api.summary("CNY", "MYR"), {
      summary_zh: null,
      generated_at: null,
      model_used: null,
    }),
  ]);

  const midmarket = rates.find((r) => r.channel_code === "midmarket");
  const newestRate = rates.reduce<LatestRate | undefined>(
    (acc, r) => (!acc || new Date(r.fetched_at) > new Date(acc.fetched_at) ? r : acc),
    undefined,
  );
  const allStale = rates.length > 0 && rates.every((r) => r.is_stale);

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col px-4 py-8 md:py-12">
      <header className="mb-8 flex flex-wrap items-baseline justify-between gap-2">
        <SiteTitle />
        {newestRate && (
          <span className="text-xs text-neutral-500">
            {zhCN.lastUpdatedPrefix} {relativeTimeZh(newestRate.fetched_at)}
          </span>
        )}
      </header>

      {allStale && (
        <div className="mb-6 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {zhCN.dataDelayedBanner}
        </div>
      )}

      <section className="mb-10">
        <RateHeadline myrPerCny={midmarket?.rate ?? null} />
      </section>

      {summary.summary_zh && (
        <p className="mb-8 text-center text-sm italic text-neutral-500">{summary.summary_zh}</p>
      )}

      <section className="mb-8">
        <RateOnlyTable rows={rates} />
      </section>

      <section className="mb-10 flex-1">
        <HomeContent initialRates={rates} />
      </section>

      <footer className="mt-auto border-t border-neutral-200 pt-6 text-xs leading-relaxed text-neutral-500">
        <p className="mb-2">{zhCN.disclaimer}</p>
        <p>
          {zhCN.dataSourcesLabel}: Frankfurter · BOC · UnionPay · Visa · Mastercard · Wise · Maybank
          · CIMB
        </p>
      </footer>
    </main>
  );
}
