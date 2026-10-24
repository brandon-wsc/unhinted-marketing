import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { EditImageDialog } from "@/features/session/components/edit-image-dialog";
import type { PreviewDraft } from "@/features/session/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const parkedDraft: PreviewDraft = {
  revision: 3,
  approval_token: "tok",
  image_url: null,
  media: [
    {
      id: "m1",
      url: null,
      plan: { format: "single", prompt: "draw the stall" },
      format: "single",
      role: "primary",
      seq: 0,
      status: "pending",
    },
    {
      id: "m2",
      url: "/media/old.png",
      plan: { format: "single", prompt: "old" },
      format: "single",
      role: "extra",
      seq: 1,
      status: "ready",
    },
  ],
  copy: { caption: "cap", hashtags: [], cta: "" },
  platform: "instagram",
  source_signals: [],
};

function renderDialog(parked: boolean) {
  return render(
    <TooltipProvider>
      <EditImageDialog
        open
        onOpenChange={vi.fn()}
        draft={parkedDraft}
        busy={false}
        parked={parked}
        onSavePlan={vi.fn()}
        onRegenImage={vi.fn()}
        onAddImage={vi.fn()}
        onRemoveImage={vi.fn()}
        onUploadImage={vi.fn()}
      />
    </TooltipProvider>,
  );
}

describe("EditImageDialog parked at image OK (ADR 0036 §4)", () => {
  it("locks pixel/media mutations and keeps plan editing open", () => {
    renderDialog(true);
    expect(screen.getByText("preview.media.editHintParked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /preview\.media\.generate/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "preview.media.add" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /preview\.media\.delete/ })).toBeDisabled();
    expect(screen.getByLabelText("preview.media.prompt")).toBeEnabled();
    expect(screen.getByRole("button", { name: "preview.media.savePlan" })).toBeDisabled(); // untouched plan — nothing to save yet
  });

  it("unlocks media mutations when not parked", () => {
    renderDialog(false);
    expect(screen.getByText("preview.media.editHint")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "preview.media.add" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /preview\.media\.delete/ })).toBeEnabled();
  });
});
