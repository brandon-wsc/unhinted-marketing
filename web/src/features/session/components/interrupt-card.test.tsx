import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { InterruptCard } from "@/features/session/components/interrupt-card";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("InterruptCard", () => {
  it("shows generate copy when idle", () => {
    render(<InterruptCard sending={false} onResume={vi.fn()} />);
    const confirm = screen.getByRole("button", { name: "chat.agent.interrupt.confirm" });
    expect(confirm).toBeEnabled();
    expect(confirm).not.toHaveAttribute("aria-busy");
  });

  it("shows spinner and working copy while generating", () => {
    render(<InterruptCard sending={true} onResume={vi.fn()} />);
    const confirm = screen.getByRole("button", { name: /chat\.agent\.interrupt\.working/ });
    expect(confirm).toBeDisabled();
    expect(confirm).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "chat.agent.interrupt.formatSingle" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "chat.agent.interrupt.formatComic" })).toBeDisabled();
  });

  it("does not resume while generating", async () => {
    const onResume = vi.fn();
    const user = userEvent.setup();
    render(<InterruptCard sending={true} onResume={onResume} />);
    await user.click(screen.getByRole("button", { name: /chat\.agent\.interrupt\.working/ }));
    expect(onResume).not.toHaveBeenCalled();
  });
});
