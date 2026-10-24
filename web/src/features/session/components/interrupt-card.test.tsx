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

  it("shows the pending image plan collapsed at the approve point", () => {
    render(
      <InterruptCard
        sending={false}
        onResume={vi.fn()}
        onDiscard={vi.fn()}
        plan={{ format: "comic_4panel", prompt: "draw the stall", beats: ["beat 1", "beat 2"] }}
      />,
    );
    const summaryRow = screen.getByText("chat.agent.interrupt.plan");
    expect(summaryRow.closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("chat.agent.interrupt.formatComic")).toBeInTheDocument();
    expect(screen.getByText("draw the stall")).toBeInTheDocument();
    expect(screen.getByText("beat 1")).toBeInTheDocument();
    expect(screen.getByText("beat 2")).toBeInTheDocument();
  });

  it("opens the copy and plan editors from the card", async () => {
    const onEditCopy = vi.fn();
    const onEditPlan = vi.fn();
    const user = userEvent.setup();
    render(
      <InterruptCard
        sending={false}
        onResume={vi.fn()}
        onDiscard={vi.fn()}
        copyPreview="今晚約埋老友打邊爐"
        onEditCopy={onEditCopy}
        onEditPlan={onEditPlan}
        plan={{ format: "single", prompt: "draw the stall", beats: [] }}
      />,
    );
    expect(screen.getByText("chat.agent.interrupt.copy")).toBeInTheDocument();
    expect(screen.getByText("今晚約埋老友打邊爐")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "chat.agent.interrupt.editCopy" }));
    expect(onEditCopy).toHaveBeenCalledOnce();

    const planBtn = screen.getByRole("button", { name: "chat.agent.interrupt.editPlan" });
    await user.click(planBtn);
    expect(onEditPlan).toHaveBeenCalledOnce();
    // The pencil is a separate hit target — it must not toggle the details.
    expect(planBtn.closest("details")).not.toHaveAttribute("open");
  });

  it("disables the edit pencils while generating", () => {
    render(
      <InterruptCard
        sending={true}
        onResume={vi.fn()}
        onDiscard={vi.fn()}
        copyPreview="cap"
        onEditCopy={vi.fn()}
        onEditPlan={vi.fn()}
        plan={{ format: "single", prompt: "x", beats: [] }}
      />,
    );
    expect(screen.getByRole("button", { name: "chat.agent.interrupt.editCopy" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "chat.agent.interrupt.editPlan" })).toBeDisabled();
  });

  it("hides the copy row when no edit handler is provided", () => {
    render(<InterruptCard sending={false} onResume={vi.fn()} onDiscard={vi.fn()} />);
    expect(screen.queryByText("chat.agent.interrupt.copy")).toBeNull();
    expect(screen.queryByRole("button", { name: "chat.agent.interrupt.editPlan" })).toBeNull();
  });

  it("discards the pending version", async () => {
    const onDiscard = vi.fn();
    const user = userEvent.setup();
    render(<InterruptCard sending={false} onResume={vi.fn()} onDiscard={onDiscard} />);
    await user.click(screen.getByRole("button", { name: "chat.agent.interrupt.discard" }));
    expect(onDiscard).toHaveBeenCalledOnce();
  });
});
