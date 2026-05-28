import HomeContent from "@/components/public/HomeContent";
import RateHeadline from "@/components/public/RateHeadline";
import RateOnlyTable from "@/components/public/RateOnlyTable";
import SiteTitle from "@/components/public/SiteTitle";
import { api, type LatestRate, type SummaryResponse } from "@/lib/api";
import { relativeTimeZh } from "@/lib/format";
import { zhCN } from "@/lib/i18n/zh-CN";

// Render fresh on every request. ISR caching was making the homepage feel
// stale by 4-14 minutes — Cloudflare was honoring s-maxage from Next.js and
// caching the HTML on top of our own 60s in-process cache. The backend can
// trivially handle every page load (a couple of small SQL queries), so the
// simplest correct answer is to drop caching entirely on this page.
export const dynamic = "force-dynamic";
export const revalidate = 0;

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
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col px-4 pb-12 pt-8 md:px-6 md:pt-12">
      {/* ---- Header ---- */}
      <header className="mb-8 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div>
          <SiteTitle />
        </div>
        {newestRate && (
          <span className="text-xs text-neutral-400">
            {zhCN.lastUpdatedPrefix} {relativeTimeZh(newestRate.fetched_at)}
          </span>
        )}
      </header>

      {/* ---- Stale banner ---- */}
      {allStale && (
        <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {zhCN.dataDelayedBanner}
        </div>
      )}

      {/* ---- Hero: mid-market headline ---- */}
      <section className="mb-8">
        <RateHeadline myrPerCny={midmarket?.rate ?? null} />
      </section>

      {/* ---- AI summary (one-liner, optional) ---- */}
      {summary.summary_zh && (
        <p className="mb-8 text-center text-sm italic leading-relaxed text-neutral-500">
          {summary.summary_zh}
        </p>
      )}

      {/* ---- Pure-rate comparison ---- */}
      <section className="mb-8">
        <RateOnlyTable rows={rates} />
      </section>

      {/* ---- Detailed comparison + chart ---- */}
      <section className="mb-12 flex-1">
        <HomeContent initialRates={rates} />
      </section>

      {/* ---- Footer ---- */}
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
