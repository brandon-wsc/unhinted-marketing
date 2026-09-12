import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  StorageConfig,
  StorageMigration,
  StorageMigrationState,
} from "@/features/company-settings/api";
import {
  formatStorageBytes,
  STORAGE_POLL_MS,
  StoragePanel,
} from "@/features/company-settings/components/storage-panel";

const { api } = vi.hoisted(() => ({
  api: {
    apiGetStorageConfig: vi.fn(),
    apiPutStorageConfig: vi.fn(),
    apiTestStorageConnection: vi.fn(),
    apiStartStorageMigration: vi.fn(),
    apiFlipStorageMigration: vi.fn(),
    apiRollbackStorageMigration: vi.fn(),
    apiCleanStorageMigration: vi.fn(),
  },
}));

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t, i18n: { language: "en" } }) };
});

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ accessToken: "tok" }),
}));

vi.mock("@/features/company-settings/api", () => ({
  apiGetStorageConfig: api.apiGetStorageConfig,
  apiPutStorageConfig: api.apiPutStorageConfig,
  apiTestStorageConnection: api.apiTestStorageConnection,
  apiStartStorageMigration: api.apiStartStorageMigration,
  apiFlipStorageMigration: api.apiFlipStorageMigration,
  apiRollbackStorageMigration: api.apiRollbackStorageMigration,
  apiCleanStorageMigration: api.apiCleanStorageMigration,
}));

function migration(
  state: StorageMigrationState,
  extra: Partial<StorageMigration> = {},
): StorageMigration {
  return {
    id: "m1",
    state,
    stats: { scanned: 10, copied: 8, skipped: 0, bytes: 2048, orphans: 2 },
    error_keys: [],
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...extra,
  };
}

function localConfig(extra: Partial<StorageConfig> = {}): StorageConfig {
  return {
    backend: "local",
    bucket: "media",
    endpoint_url: "http://localhost:9000",
    region: "us-east-1",
    public_base_url: null,
    access_key: "AKIAEXAMPLE",
    secret_last4: "ab12",
    seeded_from_env: false,
    dual_write: false,
    can_migrate: true,
    migration: null,
    ...extra,
  };
}

function renderPanel() {
  return render(
    <MemoryRouter>
      <StoragePanel companyId="c1" />
    </MemoryRouter>,
  );
}

describe("formatStorageBytes", () => {
  it("formats bytes, KB, and MB", () => {
    expect(formatStorageBytes(500)).toBe("500 B");
    expect(formatStorageBytes(2048)).toBe("2 KB");
    expect(formatStorageBytes(1.5 * 1024 * 1024)).toBe("1.5 MB");
    expect(formatStorageBytes(10 * 1024 * 1024)).toBe("10 MB");
  });
});

describe("StoragePanel", () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
    api.apiGetStorageConfig.mockReset().mockResolvedValue(localConfig());
    api.apiPutStorageConfig.mockReset();
    api.apiTestStorageConnection.mockReset();
    api.apiStartStorageMigration.mockReset();
    api.apiFlipStorageMigration.mockReset();
    api.apiRollbackStorageMigration.mockReset();
    api.apiCleanStorageMigration.mockReset();
  });

  it("shows the local form and last4 without leaking the secret", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByDisplayValue("media")).toBeInTheDocument();
    });
    expect(screen.getByText("settings.storage.badgeLocal")).toBeInTheDocument();
    const secret = screen.getByLabelText("settings.storage.secret");
    expect(secret).toHaveAttribute("type", "password");
    expect(secret).toHaveValue("");
    expect(secret).toHaveAttribute("placeholder", "••••ab12");
    expect(screen.queryByDisplayValue(/super-secret|SECRET/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.storage.start" })).toBeEnabled();
  });

  it("omits an empty secret on save so the stored key is kept", async () => {
    const user = userEvent.setup();
    api.apiPutStorageConfig.mockResolvedValue(localConfig());
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "settings.storage.save" })).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: "settings.storage.save" }));
    await waitFor(() => {
      expect(api.apiPutStorageConfig).toHaveBeenCalledWith(
        "tok",
        "c1",
        expect.objectContaining({ bucket: "media" }),
      );
    });
    expect(api.apiPutStorageConfig.mock.calls[0][2]).not.toHaveProperty("secret_key");
  });

  it("disables Start until object storage can migrate", async () => {
    api.apiGetStorageConfig.mockResolvedValue(localConfig({ can_migrate: false, bucket: "" }));
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("settings.storage.startDisabled")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "settings.storage.start" })).toBeDisabled();
  });

  it("starts a move and shows the copying cluster without cancel", async () => {
    const user = userEvent.setup();
    const copying = localConfig({
      dual_write: true,
      can_migrate: false,
      migration: migration("copying"),
    });
    api.apiStartStorageMigration.mockResolvedValue(migration("copying"));
    api.apiGetStorageConfig.mockResolvedValueOnce(localConfig()).mockResolvedValue(copying);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "settings.storage.start" })).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: "settings.storage.start" }));
    await waitFor(() => {
      expect(api.apiStartStorageMigration).toHaveBeenCalledWith("tok", "c1");
    });
    await waitFor(() => {
      expect(screen.getByText("settings.storage.copyingTitle")).toBeInTheDocument();
    });
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "common.cancel" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "settings.storage.test" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("settings.storage.bucket")).toHaveAttribute("readOnly");
  });

  it("polls copying until ready to flip", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const copying = localConfig({
      dual_write: true,
      can_migrate: false,
      migration: migration("copying"),
    });
    const ready = localConfig({
      dual_write: true,
      can_migrate: false,
      migration: migration("ready_to_flip"),
    });
    api.apiGetStorageConfig.mockResolvedValue(copying);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("settings.storage.copyingTitle")).toBeInTheDocument();
    });
    api.apiGetStorageConfig.mockResolvedValue(ready);
    await vi.advanceTimersByTimeAsync(STORAGE_POLL_MS);
    await waitFor(() => {
      expect(screen.getByText("settings.storage.readyHint")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "settings.storage.flip" })).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("confirms Switch to S3 in a dialog", async () => {
    const user = userEvent.setup();
    const ready = localConfig({
      dual_write: true,
      can_migrate: false,
      migration: migration("ready_to_flip"),
    });
    const completed = localConfig({
      backend: "s3",
      dual_write: true,
      can_migrate: false,
      migration: migration("completed"),
    });
    api.apiGetStorageConfig.mockResolvedValueOnce(ready).mockResolvedValueOnce(completed);
    api.apiFlipStorageMigration.mockResolvedValue(migration("completed"));
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "settings.storage.flip" })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "settings.storage.flip" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("settings.storage.flipTitle")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "settings.storage.flip" }));
    await waitFor(() => {
      expect(api.apiFlipStorageMigration).toHaveBeenCalledWith("tok", "c1", "m1");
    });
    await waitFor(() => {
      expect(screen.getByText("settings.storage.graceHint")).toBeInTheDocument();
    });
  });

  it("rolls back from S3 grace without a dialog", async () => {
    const user = userEvent.setup();
    const completed = localConfig({
      backend: "s3",
      dual_write: true,
      can_migrate: false,
      migration: migration("completed"),
    });
    const localAgain = localConfig({ dual_write: true, migration: migration("ready_to_flip") });
    api.apiGetStorageConfig.mockResolvedValueOnce(completed).mockResolvedValueOnce(localAgain);
    api.apiRollbackStorageMigration.mockResolvedValue(migration("ready_to_flip"));
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "settings.storage.rollback" })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "settings.storage.rollback" }));
    await waitFor(() => {
      expect(api.apiRollbackStorageMigration).toHaveBeenCalledWith("tok", "c1", "m1");
    });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("confirms clean local files in a destructive dialog", async () => {
    const user = userEvent.setup();
    const completed = localConfig({
      backend: "s3",
      dual_write: true,
      can_migrate: false,
      migration: migration("completed"),
    });
    const done = localConfig({
      backend: "s3",
      dual_write: false,
      can_migrate: false,
      migration: migration("done"),
    });
    api.apiGetStorageConfig.mockResolvedValueOnce(completed).mockResolvedValueOnce(done);
    api.apiCleanStorageMigration.mockResolvedValue(migration("done"));
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "settings.storage.clean" })).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: "settings.storage.clean" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("settings.storage.cleanTitle")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "settings.storage.clean" }));
    await waitFor(() => {
      expect(api.apiCleanStorageMigration).toHaveBeenCalledWith("tok", "c1", "m1");
    });
    await waitFor(() => {
      expect(screen.getByText("settings.storage.doneHint")).toBeInTheDocument();
    });
  });

  it("hides the migrate card on cloud S3 with no migration", async () => {
    api.apiGetStorageConfig.mockResolvedValue(
      localConfig({
        backend: "s3",
        can_migrate: false,
        secret_last4: "zz99",
        migration: null,
      }),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("settings.storage.badgeS3")).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("button", { name: "settings.storage.start" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("settings.storage.doneHint")).not.toBeInTheDocument();
  });

  it("shows a failed alert and Try again", async () => {
    api.apiGetStorageConfig.mockResolvedValue(
      localConfig({
        can_migrate: true,
        migration: migration("failed", { error: "probe failed" }),
      }),
    );
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "settings.storage.tryAgain" })).toBeEnabled();
    });
    expect(screen.getByText(/settings.storage.failed/)).toBeInTheDocument();
    expect(screen.getByText(/probe failed/)).toBeInTheDocument();
  });
});
