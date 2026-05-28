import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { zhCN } from "@/lib/i18n/zh-CN";

export const metadata: Metadata = {
  title: zhCN.siteTitleFull,
  description: zhCN.siteTagline,
  robots: { index: true, follow: true },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
