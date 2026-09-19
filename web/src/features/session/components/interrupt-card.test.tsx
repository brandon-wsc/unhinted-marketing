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

  it("confirms with the default single format", async () => {
    const onResume = vi.fn();
    const user = userEvent.setup();
    render(<InterruptCard sending={false} onResume={onResume} />);
    expect(screen.getByText("chat.agent.interrupt.lateSwitchHint")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "chat.agent.interrupt.confirm" }));
    expect(onResume).toHaveBeenCalledWith("single");
  });

  it("confirms with a late-switch comic pick", async () => {
    const onResume = vi.fn();
    const user = userEvent.setup();
    render(<InterruptCard sending={false} onResume={onResume} />);
    await user.click(screen.getByRole("button", { name: "chat.agent.interrupt.formatComic" }));
    await user.click(screen.getByRole("button", { name: "chat.agent.interrupt.confirm" }));
    expect(onResume).toHaveBeenCalledWith("comic_4panel");
  });

  it("defaults to the format already picked on the bundled card", async () => {
    const onResume = vi.fn();
    const user = userEvent.setup();
    render(<InterruptCard sending={false} defaultFormat="comic_4panel" onResume={onResume} />);
    expect(
      screen.getByRole("button", { name: "chat.agent.interrupt.formatComic" }),
    ).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "chat.agent.interrupt.confirm" }));
    expect(onResume).toHaveBeenCalledWith("comic_4panel");
  });

  it("follows defaultFormat when hydrate arrives after mount", async () => {
    const onResume = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <InterruptCard sending={false} defaultFormat={null} onResume={onResume} />,
    );
    expect(
      screen.getByRole("button", { name: "chat.agent.interrupt.formatSingle" }),
    ).toHaveAttribute("aria-pressed", "true");
    rerender(<InterruptCard sending={false} defaultFormat="comic_4panel" onResume={onResume} />);
    expect(
      screen.getByRole("button", { name: "chat.agent.interrupt.formatComic" }),
    ).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "chat.agent.interrupt.confirm" }));
    expect(onResume).toHaveBeenCalledWith("comic_4panel");
  });
});
