import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UserMenuDropdown } from "@/components/user-menu-dropdown";

const { changeLanguage, setMode, logout, navigate } = vi.hoisted(() => ({
  changeLanguage: vi.fn(),
  setMode: vi.fn(),
  logout: vi.fn().mockResolvedValue(undefined),
  navigate: vi.fn(),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigate,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("@/i18n", () => ({
  default: { changeLanguage },
}));

const { mockUser } = vi.hoisted(() => ({
  mockUser: {
    id: "u1",
    email: "ada@example.com",
    display_name: "Ada",
    is_active: true,
    platform_level: 3,
    created_at: "",
    organizations: [] as unknown[],
  },
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({
    user: mockUser,
    logout,
  }),
}));

vi.mock("@/context/theme-context", () => ({
  useTheme: () => ({
    mode: "light",
    resolved: "light",
    setMode,
  }),
}));

describe("UserMenuDropdown", () => {
  beforeEach(() => {
    changeLanguage.mockClear();
    setMode.mockClear();
    logout.mockClear();
    navigate.mockClear();
    mockUser.platform_level = 3;
  });

  it("opens and closes the menu", async () => {
    const user = userEvent.setup();
    render(<UserMenuDropdown />);

    const trigger = screen.getByRole("button", { name: /Ada/i });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(trigger);
    expect(screen.getByRole("menu")).toBeInTheDocument();

    await user.click(trigger);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("calls setMode when a theme option is selected", async () => {
    const user = userEvent.setup();
    render(<UserMenuDropdown />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));
    await user.click(screen.getByRole("menuitemradio", { name: "theme.dark" }));

    expect(setMode).toHaveBeenCalledWith("dark");
  });

  it("calls changeLanguage when a locale is selected", async () => {
    const user = userEvent.setup();
    render(<UserMenuDropdown />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));
    await user.click(screen.getByRole("menuitemradio", { name: "繁體中文（香港）" }));

    expect(changeLanguage).toHaveBeenCalledWith("zh-HK");
  });

  it("hides the admin entry for members", async () => {
    const user = userEvent.setup();
    render(<UserMenuDropdown />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));

    expect(screen.queryByRole("menuitem", { name: "admin.menuEntry" })).not.toBeInTheDocument();
  });

  it("navigates to /admin from the admin entry for admins", async () => {
    mockUser.platform_level = 9;
    const user = userEvent.setup();
    render(<UserMenuDropdown />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));
    await user.click(screen.getByRole("menuitem", { name: "admin.menuEntry" }));

    expect(navigate).toHaveBeenCalledWith("/admin");
  });
});
