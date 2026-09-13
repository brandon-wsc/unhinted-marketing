import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LoginPage } from "@/pages/login";
import { RegisterPage } from "@/pages/register";

const { apiGetInvitePreview, useSetupMock, registerMock } = vi.hoisted(() => ({
  apiGetInvitePreview: vi.fn(),
  useSetupMock: vi.fn(),
  registerMock: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("@/components/auth-layout", () => ({
  AuthLayout: ({ children, footer }: { children: ReactNode; footer?: ReactNode }) => (
    <div>
      {children}
      {footer}
    </div>
  ),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: null,
    loading: false,
    login: vi.fn(),
    register: registerMock,
  }),
}));

vi.mock("@/context/setup-context", () => ({
  useSetup: () => useSetupMock(),
}));

vi.mock("@/context/toast-context", () => ({
  useToast: () => ({ showError: vi.fn() }),
}));

vi.mock("@/features/company-settings/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/features/company-settings/api")>();
  return { ...actual, apiGetInvitePreview };
});

function onpremSetupDone() {
  useSetupMock.mockReturnValue({
    status: { setup_required: false },
    loading: false,
    deploymentMode: "onprem",
    refresh: vi.fn(),
  });
}

describe("on-prem auth gating (ADR 0026)", () => {
  beforeEach(() => {
    apiGetInvitePreview.mockReset();
    apiGetInvitePreview.mockResolvedValue({
      email: "ada@example.com",
      company_name: "Test Co",
    });
    registerMock.mockReset();
    onpremSetupDone();
  });

  it("hides the register link on login when on-prem setup is complete", async () => {
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByLabelText("common.email");
    expect(screen.queryByText("auth.login.registerLink")).not.toBeInTheDocument();
  });

  it("keeps the register link on login for invite paths", async () => {
    render(
      <MemoryRouter initialEntries={["/login?next=%2Finvite%2Ftok-1"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByDisplayValue("ada@example.com");
    expect(screen.getByText("auth.login.registerLink")).toBeInTheDocument();
  });

  it("redirects login to /setup while first-run setup is pending", async () => {
    useSetupMock.mockReturnValue({
      status: { setup_required: true },
      loading: false,
      deploymentMode: "onprem",
      refresh: vi.fn(),
    });
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/setup" element={<div>setup-page</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("setup-page")).toBeInTheDocument();
  });

  it("redirects register to /login on on-prem without an invite", async () => {
    render(
      <MemoryRouter initialEntries={["/register"]}>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/login" element={<div>login-page</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("login-page")).toBeInTheDocument();
  });

  it("sends invite_token when registering from an invite link", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/register?next=%2Finvite%2Ftok-1"]}>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByDisplayValue("ada@example.com");
    await user.type(screen.getByLabelText("auth.register.displayName"), "Ada");
    await user.type(screen.getByLabelText("auth.register.passwordHint"), "password123");
    await user.type(screen.getByLabelText("auth.register.confirmPassword"), "password123");
    await user.click(screen.getByRole("button", { name: "auth.register.submit" }));
    expect(registerMock).toHaveBeenCalledWith(
      expect.objectContaining({ invite_token: "tok-1", email: "ada@example.com" }),
    );
  });
});
