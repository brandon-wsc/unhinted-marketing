import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SetupPage } from "@/pages/setup";

const { apiRunSetup } = vi.hoisted(() => ({
  apiRunSetup: vi.fn(),
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
    accessToken: null,
    refreshAccessToken: vi.fn(),
  }),
}));

vi.mock("@/context/setup-context", () => ({
  useSetup: () => ({
    status: { setup_required: true, web_base_url: "https://mktg.example.com" },
    loading: false,
    refresh: vi.fn(),
  }),
}));

vi.mock("@/context/toast-context", () => ({
  useToast: () => ({ showError: vi.fn() }),
}));

vi.mock("@/features/setup/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/features/setup/api")>();
  return { ...actual, apiRunSetup };
});

function renderSetup() {
  return render(
    <MemoryRouter initialEntries={["/setup"]}>
      <Routes>
        <Route path="/setup" element={<SetupPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("setup wizard step 1", () => {
  beforeEach(() => {
    apiRunSetup.mockReset();
    apiRunSetup.mockResolvedValue({ access_token: "tok" });
  });

  it("marks company name optional — no required attribute", async () => {
    renderSetup();
    const org = await screen.findByLabelText("auth.register.organizationName");
    expect(org).not.toBeRequired();
    expect(screen.getByLabelText("auth.register.displayName")).toBeRequired();
  });

  it("shows inline field errors instead of submitting empty", async () => {
    const user = userEvent.setup();
    renderSetup();
    await user.click(await screen.findByRole("button", { name: "setup.next" }));
    expect(apiRunSetup).not.toHaveBeenCalled();
    // One alert per missing required field; the optional org field is silent.
    expect(screen.getAllByRole("alert")).toHaveLength(4);
    expect(screen.getByLabelText("auth.register.displayName")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByLabelText("auth.register.organizationName")).not.toHaveAttribute(
      "aria-invalid",
    );
  });

  it("advances with company name left blank", async () => {
    const user = userEvent.setup();
    renderSetup();
    await user.type(await screen.findByLabelText("auth.register.displayName"), "First Admin");
    await user.type(screen.getByLabelText("common.email"), "admin@example.com");
    await user.type(screen.getByLabelText("auth.register.passwordHint"), "password123");
    await user.type(screen.getByLabelText("auth.register.confirmPassword"), "password123");
    await user.click(screen.getByRole("button", { name: "setup.next" }));

    // Step 2 — continue submits the setup request without an org name.
    await user.click(await screen.findByRole("button", { name: "setup.next" }));
    expect(apiRunSetup).toHaveBeenCalledWith(
      expect.objectContaining({ organization_name: undefined }),
    );
  });
});
