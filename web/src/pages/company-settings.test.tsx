import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CompanySettingsPage } from "@/pages/company-settings";

const auth = vi.hoisted(() => ({
  user: null as {
    id: string;
    email: string;
    display_name: string;
    is_active: boolean;
    platform_level: number;
    created_at: string;
    organizations: { id: string; name: string; role: string }[];
  } | null,
  loading: false,
  refreshAccessToken: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/components/app-header", () => ({
  AppShell: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: auth.user,
    loading: auth.loading,
    refreshAccessToken: auth.refreshAccessToken,
  }),
}));

vi.mock("@/features/company-settings/components/voice-form", () => ({
  VoiceForm: () => <div>voice-panel</div>,
}));
vi.mock("@/features/company-settings/components/products-panel", () => ({
  ProductsPanel: () => <div>products-panel</div>,
}));
vi.mock("@/features/company-settings/components/members-panel", () => ({
  MembersPanel: () => <div>members-panel</div>,
}));
vi.mock("@/features/company-settings/components/approvals-panel", () => ({
  ApprovalsPanel: () => <div>approvals-panel</div>,
}));
vi.mock("@/features/company-settings/components/api-keys-panel", () => ({
  ApiKeysPanel: () => <div>api-keys-panel</div>,
}));
vi.mock("@/features/company-settings/components/instagram-panel", () => ({
  InstagramPanel: () => <div>instagram-panel</div>,
}));

function renderSettings(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/settings" element={<CompanySettingsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function editorUser(role: "owner" | "admin" | "member") {
  return {
    id: "u1",
    email: "ada@example.com",
    display_name: "Ada",
    is_active: true,
    platform_level: 0,
    created_at: "",
    organizations: [{ id: "c1", name: "Co", role }],
  };
}

describe("CompanySettingsPage BYOK tab", () => {
  beforeEach(() => {
    auth.loading = false;
    auth.user = editorUser("owner");
  });

  it("shows the Models tab for owners and admins", () => {
    renderSettings("/settings?tab=models");
    expect(screen.getByRole("button", { name: "settings.nav.models" })).toBeInTheDocument();
    expect(screen.getByText("api-keys-panel")).toBeInTheDocument();
  });

  it("rewrites the old api-keys tab onto models", () => {
    renderSettings("/settings?tab=api-keys");
    expect(screen.getByRole("button", { name: "settings.nav.models" })).toBeInTheDocument();
    expect(screen.getByText("api-keys-panel")).toBeInTheDocument();
  });

  it("hides the Models tab for members and falls back to voice", () => {
    auth.user = editorUser("member");
    renderSettings("/settings?tab=models");
    expect(screen.queryByRole("button", { name: "settings.nav.models" })).not.toBeInTheDocument();
    expect(screen.queryByText("api-keys-panel")).not.toBeInTheDocument();
    expect(screen.getByText("voice-panel")).toBeInTheDocument();
  });
});

describe("CompanySettingsPage Instagram tab", () => {
  beforeEach(() => {
    auth.loading = false;
    auth.user = editorUser("owner");
  });

  it("shows the Instagram tab for owners and admins", () => {
    renderSettings("/settings?tab=instagram");
    expect(screen.getByRole("button", { name: "settings.nav.instagram" })).toBeInTheDocument();
    expect(screen.getByText("instagram-panel")).toBeInTheDocument();
  });

  it("hides the Instagram tab for members and falls back to voice", () => {
    auth.user = editorUser("member");
    renderSettings("/settings?tab=instagram");
    expect(
      screen.queryByRole("button", { name: "settings.nav.instagram" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("instagram-panel")).not.toBeInTheDocument();
    expect(screen.getByText("voice-panel")).toBeInTheDocument();
  });
});
