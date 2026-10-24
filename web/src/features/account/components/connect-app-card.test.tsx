import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConnectAppCard } from "@/features/account/components/connect-app-card";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

describe("ConnectAppCard", () => {
  it("shows the MCP URL derived from the SPA origin", () => {
    render(<ConnectAppCard />);
    const input = screen.getByLabelText("account.connectAi.urlLabel");
    expect(input).toHaveValue(`${window.location.origin}/api/mcp`);
  });

  it("offers Claude and ChatGPT steps plus a Gemini note", () => {
    render(<ConnectAppCard />);
    expect(screen.getByRole("tab", { name: "Claude" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "ChatGPT" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Gemini" })).toBeInTheDocument();
    // Default tab is Claude — its first step is visible.
    expect(screen.getByText("account.connectAi.steps.claude.1")).toBeInTheDocument();
  });
});
