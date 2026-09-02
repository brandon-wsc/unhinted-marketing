import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { PreviewPanel } from "@/features/session/components/preview-panel";
import type { ConfirmSessionResponse, PreviewDraft } from "@/features/session/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}));

vi.mock("@/features/session/components/edit-copy-dialog", () => ({
  EditCopyDialog: () => null,
}));
vi.mock("@/features/session/components/edit-image-dialog", () => ({
  EditImageDialog: () => null,
}));
vi.mock("@/features/session/components/ig-preview-mock", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/features/session/components/ig-preview-mock")>();
  return {
    ...actual,
    IgPreviewMock: () => <div>ig-mock</div>,
  };
});

const noop = async () => undefined;

function draft(overrides: Partial<PreviewDraft> = {}): PreviewDraft {
  return {
    revision: 1,
    approval_token: "tok-ok-12",
    image_url: "https://cdn.example/a.png",
    media: [
      {
        id: "m1",
        url: "https://cdn.example/a.png",
        plan: {},
        format: "single",
        role: "primary",
        seq: 0,
        status: "ready",
      },
    ],
    copy: { caption: "hi", hashtags: [], cta: "" },
    platform: "instagram",
    ...overrides,
  };
}

function renderPanel(opts: {
  draft: PreviewDraft;
  confirmed?: boolean;
  confirmReceipt?: ConfirmSessionResponse | null;
  confirmError?: string | null;
}) {
  return render(
    <MemoryRouter>
      <TooltipProvider>
        <PreviewPanel
          draft={opts.draft}
          confirmed={opts.confirmed ?? false}
          confirmReceipt={opts.confirmReceipt ?? null}
          draftSaving={false}
          confirming={false}
          confirmError={opts.confirmError ?? null}
          onApply={noop}
          onConfirm={noop}
          onSavePlan={noop}
          onRegenImage={noop}
          onAddImage={noop}
          onRemoveImage={noop}
          onUploadImage={noop}
        />
      </TooltipProvider>
    </MemoryRouter>,
  );
}

describe("PreviewPanel receipts", () => {
  it("disables Confirm and shows the image-required hint for copy-only drafts", () => {
    renderPanel({
      draft: draft({ image_url: null, media: [] }),
    });
    expect(screen.getByRole("button", { name: "preview.confirm" })).toBeDisabled();
    expect(screen.getByText("preview.gate.imageRequired")).toBeInTheDocument();
    expect(screen.queryByText("preview.receipt.publishedBadge")).not.toBeInTheDocument();
  });

  it("shows a failed receipt instead of a success wash", () => {
    renderPanel({
      draft: draft(),
      confirmReceipt: {
        receipt_id: "r-fail",
        status: "failed",
        tool_name: "publish_social_post",
        idempotency_key: "idem-fail",
        error_kind: "platform_error",
      },
    });
    expect(screen.getByText("preview.receipt.failedTitle")).toBeInTheDocument();
    expect(screen.getByText("preview.receipt.error.platform_error")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "preview.receipt.retry" })).toBeInTheDocument();
    expect(screen.queryByText("preview.receipt.publishedBadge")).not.toBeInTheDocument();
    expect(screen.queryByText("preview.confirmDone")).not.toBeInTheDocument();
  });

  it("shows the Instagram permalink on a published receipt", () => {
    renderPanel({
      draft: draft(),
      confirmed: true,
      confirmReceipt: {
        receipt_id: "r-pub",
        status: "published",
        tool_name: "publish_social_post",
        idempotency_key: "idem-pub",
        permalink: "https://www.instagram.com/p/ABC/",
      },
    });
    expect(screen.getByText("preview.receipt.publishedTitle")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "preview.receipt.viewOnInstagram" });
    expect(link).toHaveAttribute("href", "https://www.instagram.com/p/ABC/");
    expect(screen.getByText("preview.receipt.publishedBadge")).toBeInTheDocument();
  });

  it("keeps the stubbed success receipt", () => {
    renderPanel({
      draft: draft(),
      confirmed: true,
      confirmReceipt: {
        receipt_id: "r-stub",
        status: "stubbed",
        tool_name: "publish_social_post",
        idempotency_key: "idem-stub",
      },
    });
    expect(screen.getByText("preview.confirmDone")).toBeInTheDocument();
    expect(screen.getByText("preview.confirmReceipt")).toBeInTheDocument();
  });

  it("links to Instagram settings when the account is not connected", () => {
    renderPanel({
      draft: draft(),
      confirmError: "social_account_not_connected",
    });
    expect(screen.getByText("preview.gate.notConnected")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "preview.gate.openSettings" });
    expect(link).toHaveAttribute("href", "/settings?tab=instagram");
  });
});
