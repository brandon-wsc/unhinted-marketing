import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LoginPage } from "@/pages/login";
import { RegisterPage } from "@/pages/register";

const { apiGetInvitePreview } = vi.hoisted(() => ({
  apiGetInvitePreview: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("@/components/auth-layout", () => ({
  AuthLayout: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: null,
    loading: false,
    login: vi.fn(),
    register: vi.fn(),
  }),
}));

vi.mock("@/context/toast-context", () => ({
  useToast: () => ({ showError: vi.fn() }),
}));

vi.mock("@/features/company-settings/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/features/company-settings/api")>();
  return { ...actual, apiGetInvitePreview };
});

describe("login/register invite prefill", () => {
  beforeEach(() => {
    apiGetInvitePreview.mockReset();
    apiGetInvitePreview.mockResolvedValue({
      email: "ada@example.com",
      company_name: "Test Co",
    });
  });

  it("locks login email from invite preview", async () => {
    render(
      <MemoryRouter initialEntries={["/login?next=%2Finvite%2Ftok-1"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </MemoryRouter>,
    );
    const email = await screen.findByDisplayValue("ada@example.com");
    expect(email).toHaveAttribute("readOnly");
  });

  it("locks register email and hides company name", async () => {
    render(
      <MemoryRouter initialEntries={["/register?next=%2Finvite%2Ftok-1"]}>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
        </Routes>
      </MemoryRouter>,
    );
    const email = await screen.findByDisplayValue("ada@example.com");
    expect(email).toHaveAttribute("readOnly");
    expect(screen.queryByLabelText("auth.register.organizationName")).not.toBeInTheDocument();
  });
});
