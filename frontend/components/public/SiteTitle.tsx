"use client";

import { zhCN } from "@/lib/i18n/zh-CN";

/**
 * Small component so Vitest can render it (Vitest cannot render Server
 * Components). Reused by the admin login screen at smaller size.
 *
 * Visual: 'CNY → MYR Rate' with the arrow rendered slightly muted so the
 * two currency codes pop. Tracking is tight so it feels confident.
 */

type Props = {
  size?: "lg" | "md";
};

export default function SiteTitle({ size = "lg" }: Props) {
  const cls =
    size === "lg"
      ? "text-2xl md:text-3xl font-semibold tracking-tight"
      : "text-base font-semibold tracking-tight";
  // Split the title so the arrow can be colored separately.
  // Kept defensive: if the string is ever changed without an arrow, just
  // render it plain. The test asserts the heading's accessible name equals
  // zhCN.siteTitle, so the full text must remain in the DOM.
  const parts = zhCN.siteTitle.split(" → ");
  const hasArrow = parts.length === 2;
  return (
    <h1 className={cls}>
      {hasArrow ? (
        <>
          {parts[0]} <span className="text-neutral-400">→</span> {parts[1]}
        </>
      ) : (
        zhCN.siteTitle
      )}
    </h1>
  );
}
