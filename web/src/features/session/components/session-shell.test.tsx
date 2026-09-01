import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { SessionShell } from "@/features/session/components/session-shell";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/components/ui/resizable", () => ({
  ResizablePanelGroup: ({ children, className }: { children?: ReactNode; className?: string }) => (
    <div data-testid="panel-group" className={className}>
      {children}
    </div>
  ),
  ResizablePanel: ({
    children,
    className,
    id,
  }: {
    children?: ReactNode;
    className?: string;
    id?: string;
  }) => (
    <div data-testid={`panel-${id}`} className={className}>
      {children}
    </div>
  ),
  ResizableHandle: ({
    className,
    "aria-label": label,
  }: {
    className?: string;
    "aria-label"?: string;
  }) => (
    <button type="button" data-testid="resize-handle" aria-label={label} className={className} />
  ),
}));

const slots = {
  history: <div>history-slot</div>,
  historyPage: <div>history-page-slot</div>,
  chat: <div>chat-slot</div>,
  preview: <div>preview-slot</div>,
};

describe("SessionShell", () => {
  it("shows history + chat and no resize handle when split without preview", () => {
    render(
      <SessionShell
        shellRef={{ current: null }}
        layoutMode="split"
        pagedPane="chat"
        previewReady={false}
        historyCollapsed={false}
        shellWidth={1440}
        chatRatio={0.4}
        onChatRatioChange={() => undefined}
        {...slots}
        preview={null}
      />,
    );
    expect(screen.getByText("history-slot")).toBeInTheDocument();
    expect(screen.getByText("chat-slot")).toBeInTheDocument();
    expect(screen.queryByText("preview-slot")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("chat.shell.resize")).not.toBeInTheDocument();
  });

  it("shows a resize handle when split and preview are ready", () => {
    render(
      <SessionShell
        shellRef={{ current: null }}
        layoutMode="split"
        pagedPane="chat"
        previewReady
        historyCollapsed={false}
        shellWidth={1440}
        chatRatio={0.4}
        onChatRatioChange={() => undefined}
        {...slots}
      />,
    );
    expect(screen.getByText("chat-slot")).toBeInTheDocument();
    expect(screen.getByText("preview-slot")).toBeInTheDocument();
    expect(screen.getByLabelText("chat.shell.resize")).toBeInTheDocument();
    expect(screen.getByLabelText("chat.shell.resize")).not.toHaveClass("hidden");
  });

  it("keeps preview mounted (hidden) in paged chat and hides the handle", () => {
    render(
      <SessionShell
        shellRef={{ current: null }}
        layoutMode="paged"
        pagedPane="chat"
        previewReady
        historyCollapsed={false}
        shellWidth={700}
        chatRatio={0.4}
        onChatRatioChange={() => undefined}
        {...slots}
      />,
    );
    expect(screen.queryByText("history-page-slot")).not.toBeInTheDocument();
    expect(screen.getByText("chat-slot")).toBeInTheDocument();
    expect(screen.getByText("preview-slot")).toBeInTheDocument();
    expect(screen.getByLabelText("chat.shell.resize")).toHaveClass("hidden");
  });

  it("shows the record page in paged record mode", () => {
    render(
      <SessionShell
        shellRef={{ current: null }}
        layoutMode="paged"
        pagedPane="record"
        previewReady={false}
        historyCollapsed={false}
        shellWidth={390}
        chatRatio={0.4}
        onChatRatioChange={() => undefined}
        {...slots}
        preview={null}
      />,
    );
    expect(screen.getByText("history-page-slot")).toBeInTheDocument();
    expect(screen.queryByText("history-slot")).not.toBeInTheDocument();
    expect(screen.getByTestId("panel-group")).toHaveClass("hidden");
  });
});
