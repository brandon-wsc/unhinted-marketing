import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UserMenu } from "@/components/user-menu";

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
    setMode,
  }),
}));

function mockMobileViewport(matches: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
}

describe("UserMenu (desktop dropdown)", () => {
  beforeEach(() => {
    mockMobileViewport(false);
    changeLanguage.mockClear();
    setMode.mockClear();
    logout.mockClear();
    navigate.mockClear();
    mockUser.platform_level = 3;
  });

  it("opens and closes the menu", async () => {
    const user = userEvent.setup();
    render(<UserMenu />);

    const trigger = screen.getByRole("button", { name: /Ada/i });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(trigger);
    expect(screen.getByRole("menu")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("toggles dark mode via the theme switch", async () => {
    const user = userEvent.setup();
    render(<UserMenu />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));
    await user.click(screen.getByRole("switch", { name: "theme.label" }));

    expect(setMode).toHaveBeenCalledWith("dark");
  });

  it("calls changeLanguage when a locale is selected", async () => {
    const user = userEvent.setup();
    render(<UserMenu />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));
    expect(screen.getByRole("menuitemradio", { name: "繁體中文（香港）" })).toBeInTheDocument();
    expect(screen.getByRole("menuitemradio", { name: "English" })).toBeInTheDocument();
    await user.click(screen.getByRole("menuitemradio", { name: "繁體中文（香港）" }));

    expect(changeLanguage).toHaveBeenCalledWith("zh-HK");
  });

  it("hides the system entry for members", async () => {
    const user = userEvent.setup();
    render(<UserMenu />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));

    expect(screen.queryByRole("menuitem", { name: "system.menuEntry" })).not.toBeInTheDocument();
  });

  it("navigates to /settings from company settings", async () => {
    const user = userEvent.setup();
    render(<UserMenu />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));
    await user.click(screen.getByRole("menuitem", { name: "settings.menuEntry" }));

    expect(navigate).toHaveBeenCalledWith("/settings");
  });

  it("navigates to /system from the system entry for platform operators", async () => {
    mockUser.platform_level = 9;
    const user = userEvent.setup();
    render(<UserMenu />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));
    await user.click(screen.getByRole("menuitem", { name: "system.menuEntry" }));

    expect(navigate).toHaveBeenCalledWith("/system");
  });
});

describe("UserMenu (mobile dialog)", () => {
  beforeEach(() => {
    mockMobileViewport(true);
    changeLanguage.mockClear();
    setMode.mockClear();
    logout.mockClear();
    navigate.mockClear();
    mockUser.platform_level = 3;
  });

  it("opens the whole menu as a dialog and closes via the X icon", async () => {
    const user = userEvent.setup();
    render(<UserMenu />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "theme.label" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "header.menu.close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("toggles dark mode via the theme switch", async () => {
    const user = userEvent.setup();
    render(<UserMenu />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));
    await user.click(screen.getByRole("switch", { name: "theme.label" }));

    expect(setMode).toHaveBeenCalledWith("dark");
  });

  it("calls changeLanguage when a locale row is selected", async () => {
    const user = userEvent.setup();
    render(<UserMenu />);

    await user.click(screen.getByRole("button", { name: /Ada/i }));
    await user.click(screen.getByRole("button", { name: "繁體中文（香港）" }));

    expect(changeLanguage).toHaveBeenCalledWith("zh-HK");
  });
});
