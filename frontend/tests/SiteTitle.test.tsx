import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SiteTitle from "@/components/public/SiteTitle";
import { zhCN } from "@/lib/i18n/zh-CN";

describe("<SiteTitle>", () => {
  it("renders the i18n site title", () => {
    render(<SiteTitle />);
    expect(screen.getByRole("heading", { name: zhCN.siteTitle })).toBeInTheDocument();
  });

  it("supports the md size variant", () => {
    render(<SiteTitle size="md" />);
    const h = screen.getByRole("heading");
    expect(h.className).toContain("text-lg");
  });
});
