import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { InstagramPanel } from "@/features/company-settings/components/instagram-panel";

const { api } = vi.hoisted(() => ({
  api: {
    apiListSocialAccounts: vi.fn(),
    apiUpsertInstagramAccount: vi.fn(),
    apiDisconnectInstagramAccount: vi.fn(),
  },
}));

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}));

vi.mock("@/features/company-settings/api", () => ({
  apiListSocialAccounts: api.apiListSocialAccounts,
  apiUpsertInstagramAccount: api.apiUpsertInstagramAccount,
  apiDisconnectInstagramAccount: api.apiDisconnectInstagramAccount,
}));

const connected = {
  id: "sa-1",
  company_id: "c1",
  platform: "instagram" as const,
  ig_user_id: "17841400000000000",
  token_last4: "ab12",
  expires_at: "2099-01-01T00:00:00Z",
  last_verified_at: null,
  last_error_kind: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderPanel() {
  return render(
    <TooltipProvider>
      <InstagramPanel companyId="c1" />
    </TooltipProvider>,
  );
}

describe("InstagramPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.apiListSocialAccounts.mockReset().mockResolvedValue([]);
    api.apiUpsertInstagramAccount.mockReset();
    api.apiDisconnectInstagramAccount.mockReset();
  });

  it("shows the empty paste form when no account is connected", async () => {
    api.apiListSocialAccounts.mockResolvedValue([]);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByLabelText("settings.instagram.igUserId")).toBeInTheDocument();
    });
    expect(screen.getByLabelText("settings.instagram.accessToken")).toBeInTheDocument();
    expect(screen.queryByText("••••ab12")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.instagram.save" })).toBeDisabled();
  });

  it("shows last4 only on a connected account", async () => {
    api.apiListSocialAccounts.mockResolvedValue([connected]);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("••••ab12")).toBeInTheDocument();
    });
    expect(screen.getByText("settings.instagram.connected")).toBeInTheDocument();
    expect(screen.getByText(connected.ig_user_id)).toBeInTheDocument();
    expect(screen.queryByDisplayValue(/IGQ|secret-token/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("settings.instagram.accessToken")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.instagram.rotate" })).toBeInTheDocument();
  });

  it("shows the expired alert and update form", async () => {
    api.apiListSocialAccounts.mockResolvedValue([
      { ...connected, expires_at: "2020-01-01T00:00:00Z" },
    ]);
    renderPanel();
    await waitFor(() => {
      expect(screen.getAllByText("settings.instagram.expiredTitle").length).toBeGreaterThan(0);
    });
    expect(screen.getByLabelText("settings.instagram.accessToken")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.instagram.update" })).toBeDisabled();
  });

  it("saves a pasted token then hides the raw value", async () => {
    const user = userEvent.setup();
    api.apiListSocialAccounts.mockResolvedValue([]);
    api.apiUpsertInstagramAccount.mockResolvedValue(connected);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByLabelText("settings.instagram.igUserId")).toBeInTheDocument();
    });
    await user.type(screen.getByLabelText("settings.instagram.igUserId"), connected.ig_user_id);
    await user.type(screen.getByLabelText("settings.instagram.accessToken"), "secret-token-value");
    await user.click(screen.getByRole("button", { name: "settings.instagram.save" }));
    await waitFor(() => {
      expect(api.apiUpsertInstagramAccount).toHaveBeenCalledWith("tok", "c1", {
        ig_user_id: connected.ig_user_id,
        access_token: "secret-token-value",
        expires_at: null,
      });
    });
    expect(screen.getByText("••••ab12")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("secret-token-value")).not.toBeInTheDocument();
  });
});
