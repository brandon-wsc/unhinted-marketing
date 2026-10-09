import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SettingsNavItem } from "./settings-nav-item";

describe("SettingsNavItem", () => {
  it("keeps the width reserver out of the accessible name", () => {
    render(<SettingsNavItem active={false} label="品牌聲線" />);
    const button = screen.getByRole("button", { name: "品牌聲線" });
    expect(button).not.toHaveAttribute("aria-current");
    expect(button.querySelector("[aria-hidden]")).toHaveClass("invisible", "font-medium");
  });

  it("marks the active item as the current page", () => {
    render(<SettingsNavItem active label="品牌聲線" />);
    expect(screen.getByRole("button", { name: "品牌聲線" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
