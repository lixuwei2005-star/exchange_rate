"use client";

/**
 * SiteTitle is a small Client Component so Vitest can render it (Vitest cannot
 * render Server Components). It's also reused by the admin login screen.
 */

import { zhCN } from "@/lib/i18n/zh-CN";

type Props = {
  size?: "lg" | "md";
};

export default function SiteTitle({ size = "lg" }: Props) {
  const cls =
    size === "lg" ? "text-2xl md:text-3xl font-bold tracking-tight" : "text-lg font-semibold";
  return <h1 className={cls}>{zhCN.siteTitle}</h1>;
}
