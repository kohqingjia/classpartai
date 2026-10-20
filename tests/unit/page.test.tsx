import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Page } from "#/components/custom/page";

describe("Page component", () => {
  it("renders children without a header when no header props are given", () => {
    render(
      <Page>
        <p>content</p>
      </Page>
    );

    expect(screen.getByText("content")).toBeTruthy();
    expect(screen.queryByRole("heading")).toBeNull();
  });

  it("renders optional eyebrow, title, and description", () => {
    render(
      <Page eyebrow="Settings" title="Account" description="Manage your account">
        <p>content</p>
      </Page>
    );

    expect(screen.getByText("Settings")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Account" })).toBeTruthy();
    expect(screen.getByText("Manage your account")).toBeTruthy();
  });

  it("applies the width preset and lets className override defaults", () => {
    render(
      <Page width="sm" className="py-20">
        <p>content</p>
      </Page>
    );

    const main = screen.getByRole("main");
    expect(main.className).toContain("max-w-sm");
    expect(main.className).toContain("py-20");
    expect(main.className).not.toContain("py-16");
  });
});
