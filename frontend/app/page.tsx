import SiteTitle from "@/components/public/SiteTitle";
import { zhCN } from "@/lib/i18n/zh-CN";

export const revalidate = 300; // ISR 5 min

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col px-4 py-8 md:py-12">
      <header className="mb-12">
        <SiteTitle />
        <p className="mt-2 text-sm text-neutral-600">{zhCN.siteTagline}</p>
      </header>

      <section className="flex-1">
        <div className="rounded-lg border border-neutral-200 bg-white p-8 text-center">
          <p className="text-lg text-neutral-500">{zhCN.comingSoon}</p>
        </div>
      </section>

      <footer className="mt-12 border-t border-neutral-200 pt-6 text-xs leading-relaxed text-neutral-500">
        <p>{zhCN.disclaimer}</p>
      </footer>
    </main>
  );
}
