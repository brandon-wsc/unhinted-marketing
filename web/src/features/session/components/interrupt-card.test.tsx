import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { InterruptCard } from "@/features/session/components/interrupt-card";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("InterruptCard", () => {
  it("shows generate copy when idle", () => {
    render(<InterruptCard sending={false} onResume={vi.fn()} onDiscard={vi.fn()} />);
    const confirm = screen.getByRole("button", { name: "chat.agent.interrupt.confirm" });
    expect(confirm).toBeEnabled();
    expect(confirm).not.toHaveAttribute("aria-busy");
    expect(screen.getByRole("button", { name: "chat.agent.interrupt.discard" })).toBeEnabled();
  });

  it("shows spinner and working copy while generating", () => {
    render(<InterruptCard sending={true} onResume={vi.fn()} onDiscard={vi.fn()} />);
    const confirm = screen.getByRole("button", { name: /chat\.agent\.interrupt\.working/ });
    expect(confirm).toBeDisabled();
    expect(confirm).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "chat.agent.interrupt.discard" })).toBeDisabled();
  });

  it("does not resume or discard while generating", async () => {
    const onResume = vi.fn();
    const onDiscard = vi.fn();
    const user = userEvent.setup();
    render(<InterruptCard sending={true} onResume={onResume} onDiscard={onDiscard} />);
    await user.click(screen.getByRole("button", { name: /chat\.agent\.interrupt\.working/ }));
    await user.click(screen.getByRole("button", { name: "chat.agent.interrupt.discard" }));
    expect(onResume).not.toHaveBeenCalled();
    expect(onDiscard).not.toHaveBeenCalled();
  });

  it("executes without a format argument", async () => {
    const onResume = vi.fn();
    const user = userEvent.setup();
    render(<InterruptCard sending={false} onResume={onResume} onDiscard={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "chat.agent.interrupt.formatSingle" })).toBeNull();
    expect(screen.queryByRole("button", { name: "chat.agent.interrupt.formatComic" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "chat.agent.interrupt.confirm" }));
    expect(onResume).toHaveBeenCalledWith();
  });

  it("discards the pending version", async () => {
    const onDiscard = vi.fn();
    const user = userEvent.setup();
    render(<InterruptCard sending={false} onResume={vi.fn()} onDiscard={onDiscard} />);
    await user.click(screen.getByRole("button", { name: "chat.agent.interrupt.discard" }));
    expect(onDiscard).toHaveBeenCalledOnce();
  });
});
