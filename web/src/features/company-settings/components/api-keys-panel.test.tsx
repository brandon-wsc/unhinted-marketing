import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiKeysPanel } from "@/features/company-settings/components/api-keys-panel";

const { ByokDependentsError, api } = vi.hoisted(() => {
  class ByokDependentsError extends Error {
    conflict: { models: { id: string; model_id: string; slots: string[] }[]; slots: string[] };
    constructor(conflict: {
      models: { id: string; model_id: string; slots: string[] }[];
      slots: string[];
    }) {
      super("This key or model is still in use");
      this.name = "ByokDependentsError";
      this.conflict = conflict;
    }
  }
  return {
    ByokDependentsError,
    api: {
      apiListByokProviders: vi.fn(),
      apiListByokModels: vi.fn(),
      apiGetByokRouting: vi.fn(),
      apiDeleteByokProvider: vi.fn(),
      apiDeleteByokModel: vi.fn(),
      apiTestByokProvider: vi.fn(),
      apiTestByokModel: vi.fn(),
      apiPatchByokProvider: vi.fn(),
      apiPutByokRouting: vi.fn(),
      apiCreateByokProvider: vi.fn(),
      apiCreateByokModel: vi.fn(),
      apiListByokProviderCatalog: vi.fn(),
    },
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { last4?: string; modelId?: string }) => {
      if (opts?.last4) return `masked-${opts.last4}`;
      if (opts?.modelId) return `Company: ${opts.modelId}`;
      return key;
    },
  }),
}));

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}));

vi.mock("@/features/company-settings/api", () => ({
  ByokDependentsError,
  ...api,
}));

const provider = {
  id: "p1",
  label: "OpenRouter",
  provider_type: "openai_compatible" as const,
  key_last4: "abcd",
  api_base: "https://openrouter.ai/api/v1",
  last_verified_at: "2026-01-01T00:00:00Z",
  last_error_kind: null,
  verified: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const chatModel = {
  id: "m-chat",
  provider_id: "p1",
  provider_label: "OpenRouter",
  provider_key_last4: "abcd",
  model_id: "deepseek-v4-flash",
  capability: "chat" as const,
  capability_source: "inferred" as const,
  last_verified_at: "2026-01-01T00:00:00Z",
  last_error_kind: null,
  verified: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const imageModel = {
  ...chatModel,
  id: "m-image",
  model_id: "seedream",
  capability: "image" as const,
};

const envRouting = {
  slots: [
    { slot: "cheap" as const, source: "env" as const, registry_id: null, model_id: "gpt-4o-mini" },
    { slot: "medium" as const, source: "env" as const, registry_id: null, model_id: "gpt-4o" },
    {
      slot: "strong" as const,
      source: "org" as const,
      registry_id: "m-chat",
      model_id: "deepseek-v4-flash",
    },
    { slot: "image" as const, source: "env" as const, registry_id: null, model_id: null },
  ],
};

describe("ApiKeysPanel", () => {
  beforeEach(() => {
    api.apiListByokProviders.mockReset().mockResolvedValue([provider]);
    api.apiListByokModels.mockReset().mockResolvedValue([chatModel, imageModel]);
    api.apiGetByokRouting.mockReset().mockResolvedValue(envRouting);
    api.apiDeleteByokProvider.mockReset();
    api.apiTestByokModel.mockReset();
    api.apiListByokProviderCatalog.mockReset().mockResolvedValue({ fetchable: false, models: [] });
  });

  it("shows keys, models, and env vs company routing helpers", async () => {
    render(<ApiKeysPanel companyId="c1" />);
    expect(await screen.findByText("OpenRouter")).toBeInTheDocument();
    expect(screen.getAllByText("deepseek-v4-flash").length).toBeGreaterThan(0);
    expect(screen.getByText("seedream")).toBeInTheDocument();
    expect(screen.getByText("Company: deepseek-v4-flash")).toBeInTheDocument();
    expect(screen.getAllByText("settings.apiKeys.routing.helperEnv").length).toBeGreaterThan(0);
  });

  it("opens the add-model wizard", async () => {
    const user = userEvent.setup();
    render(<ApiKeysPanel companyId="c1" />);
    await screen.findByText("OpenRouter");
    await user.click(screen.getByRole("button", { name: "settings.apiKeys.addModel" }));
    expect(await screen.findByText("settings.apiKeys.wizard.title")).toBeInTheDocument();
  });

  it("warns before testing an image model", async () => {
    const user = userEvent.setup();
    render(<ApiKeysPanel companyId="c1" />);
    const row = (await screen.findByText("seedream")).closest("tr");
    expect(row).toBeTruthy();
    await user.click(
      within(row as HTMLElement).getByRole("button", { name: "settings.apiKeys.actions.test" }),
    );
    expect(await screen.findByText("settings.apiKeys.models.imageTestTitle")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "settings.apiKeys.models.imageTestConfirm" }),
    );
    await waitFor(() => {
      expect(api.apiTestByokModel).toHaveBeenCalledWith("tok", "c1", "m-image", true);
    });
  });

  it("lists dependents after 409 then force-deletes", async () => {
    const user = userEvent.setup();
    api.apiDeleteByokProvider
      .mockRejectedValueOnce(
        new ByokDependentsError({
          models: [{ id: "m-chat", model_id: "deepseek-v4-flash", slots: ["strong"] }],
          slots: ["strong"],
        }),
      )
      .mockResolvedValueOnce(undefined);
    render(<ApiKeysPanel companyId="c1" />);
    const row = (await screen.findByText("OpenRouter")).closest("tr");
    await user.click(
      within(row as HTMLElement).getByRole("button", { name: "settings.apiKeys.actions.delete" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await user.click(
      within(dialog).getByRole("button", { name: "settings.apiKeys.actions.delete" }),
    );
    expect(await screen.findByText("settings.apiKeys.delete.dependents")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "settings.apiKeys.delete.force" }));
    await waitFor(() => {
      expect(api.apiDeleteByokProvider).toHaveBeenNthCalledWith(1, "tok", "c1", "p1", false);
      expect(api.apiDeleteByokProvider).toHaveBeenNthCalledWith(2, "tok", "c1", "p1", true);
    });
  });
});
