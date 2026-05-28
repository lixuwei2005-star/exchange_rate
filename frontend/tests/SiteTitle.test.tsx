import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SiteTitle from "@/components/public/SiteTitle";
import { zhCN } from "@/lib/i18n/zh-CN";

describe("<SiteTitle>", () => {
  it("renders the i18n site title", () => {
    render(<SiteTitle />);
    expect(screen.getByRole("heading", { name: zhCN.siteTitle })).toBeInTheDocument();
  });

  it("md variant uses a smaller font than the default lg", () => {
    render(<SiteTitle size="md" />);
    const h = screen.getByRole("heading");
    // md is currently text-base (vs lg's text-2xl/3xl) — assert the smaller
    // utility class is present without pinning to an exact value.
    expect(h.className).toMatch(/\btext-(xs|sm|base)\b/);
    expect(h.className).not.toMatch(/\btext-(xl|2xl|3xl)\b/);
  });
});
