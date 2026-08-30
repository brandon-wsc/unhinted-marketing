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

const createdProvider = {
  id: "p-new",
  label: "My key",
  provider_type: "openai" as const,
  key_last4: "key1",
  api_base: null,
  last_verified_at: null,
  last_error_kind: null,
  verified: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const createdModel = {
  id: "m-new",
  provider_id: "p1",
  provider_label: "OpenRouter",
  provider_key_last4: "abcd",
  model_id: "gpt-x",
  capability: "chat" as const,
  capability_source: "inferred" as const,
  last_verified_at: null,
  last_error_kind: null,
  verified: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
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
    api.apiDeleteByokModel.mockReset();
    api.apiTestByokModel.mockReset();
    api.apiCreateByokProvider.mockReset();
    api.apiCreateByokModel.mockReset();
    api.apiPutByokRouting.mockReset().mockResolvedValue(envRouting);
    api.apiListByokProviderCatalog.mockReset().mockResolvedValue({ fetchable: false, models: [] });
  });

  it("shows keys, models, and env vs company routing helpers", async () => {
    render(<ApiKeysPanel companyId="c1" />);
    expect(await screen.findByText("OpenRouter")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.apiKeys.addKey" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.apiKeys.addModel" })).toBeEnabled();
    expect(screen.getAllByText("deepseek-v4-flash").length).toBeGreaterThan(0);
    expect(screen.getByText("seedream")).toBeInTheDocument();
    expect(screen.getByText("Company: deepseek-v4-flash")).toBeInTheDocument();
    expect(screen.getAllByText("settings.apiKeys.routing.helperEnv").length).toBeGreaterThan(0);
  });

  it("opens the add-model dialog from the models section", async () => {
    const user = userEvent.setup();
    render(<ApiKeysPanel companyId="c1" />);
    await screen.findByText("OpenRouter");
    await user.click(screen.getByRole("button", { name: "settings.apiKeys.addModel" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("settings.apiKeys.addModel")).toBeInTheDocument();
    expect(within(dialog).getByText("settings.apiKeys.addModelHint")).toBeInTheDocument();
    expect(
      await within(dialog).findByLabelText("settings.apiKeys.wizard.modelId"),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByLabelText("settings.apiKeys.wizard.keyExisting"),
    ).not.toBeInTheDocument();
  });

  it("does not close the add-model dialog on overlay click", async () => {
    const user = userEvent.setup();
    render(<ApiKeysPanel companyId="c1" />);
    await screen.findByText("OpenRouter");
    await user.click(screen.getByRole("button", { name: "settings.apiKeys.addModel" }));
    expect(await screen.findByText("settings.apiKeys.addModelHint")).toBeInTheDocument();
    const overlay = document.querySelector('[data-slot="dialog-overlay"]');
    expect(overlay).toBeTruthy();
    await user.click(overlay as Element);
    expect(screen.getByText("settings.apiKeys.addModelHint")).toBeInTheDocument();
  });

  it("shows add-key validation errors inside the dialog", async () => {
    const user = userEvent.setup();
    render(<ApiKeysPanel companyId="c1" />);
    await user.click(await screen.findByRole("button", { name: "settings.apiKeys.addKey" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "common.save" }));
    expect(
      await within(dialog).findByText("settings.apiKeys.errors.labelRequired"),
    ).toBeInTheDocument();
    expect(api.apiCreateByokProvider).not.toHaveBeenCalled();
  });

  it("disables add model until a key exists", async () => {
    api.apiListByokProviders.mockResolvedValue([]);
    api.apiListByokModels.mockResolvedValue([]);
    render(<ApiKeysPanel companyId="c1" />);
    expect(await screen.findByRole("button", { name: "settings.apiKeys.addModel" })).toBeDisabled();
    expect(screen.getByText("settings.apiKeys.models.emptyNeedsKey")).toBeInTheDocument();
  });

  it("adds a key and closes without opening add-model", async () => {
    const user = userEvent.setup();
    api.apiListByokProviders.mockResolvedValue([]);
    api.apiListByokModels.mockResolvedValue([]);
    api.apiCreateByokProvider.mockResolvedValue(createdProvider);
    render(<ApiKeysPanel companyId="c1" />);
    expect(await screen.findByRole("button", { name: "settings.apiKeys.addModel" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "settings.apiKeys.addKey" }));
    api.apiListByokProviders.mockResolvedValue([createdProvider]);
    await user.type(await screen.findByLabelText("settings.apiKeys.wizard.label"), "My key");
    await user.type(screen.getByLabelText("settings.apiKeys.wizard.apiKey"), "sk-test");
    await user.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() => {
      expect(api.apiCreateByokProvider).toHaveBeenCalledWith("tok", "c1", {
        label: "My key",
        provider_type: "openai",
        api_key: "sk-test",
        api_base: null,
      });
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("settings.apiKeys.addModelHint")).not.toBeInTheDocument();
    expect(api.apiCreateByokModel).not.toHaveBeenCalled();
  });

  it("saves a model without calling routing", async () => {
    const user = userEvent.setup();
    api.apiCreateByokModel.mockResolvedValue(createdModel);
    render(<ApiKeysPanel companyId="c1" />);
    await user.click(await screen.findByRole("button", { name: "settings.apiKeys.addModel" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(
      await within(dialog).findByLabelText("settings.apiKeys.wizard.modelId"),
      "gpt-x",
    );
    await user.click(within(dialog).getByRole("button", { name: "common.save" }));
    await waitFor(() => {
      expect(api.apiCreateByokModel).toHaveBeenCalledWith("tok", "c1", {
        provider_id: "p1",
        model_id: "gpt-x",
        capability: "chat",
        capability_source: "inferred",
      });
    });
    expect(api.apiPutByokRouting).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
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
