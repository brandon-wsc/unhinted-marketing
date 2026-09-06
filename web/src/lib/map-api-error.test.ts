import type { TFunction } from "i18next";
import { describe, expect, it, vi } from "vitest";
import { mapApiError } from "@/lib/map-api-error";

describe("mapApiError", () => {
  const t = vi.fn((key: string, opts?: { status?: string }) => {
    if (opts?.status !== undefined) return `${key}:${opts.status}`;
    return `i18n:${key}`;
  }) as unknown as TFunction;

  it("maps known API messages to i18n keys", () => {
    expect(mapApiError("Invalid email address", t)).toBe("i18n:errors.invalidEmail");
    expect(mapApiError("Password must be at least 8 characters", t)).toBe(
      "i18n:errors.passwordTooShort",
    );
    expect(mapApiError("Email already registered", t)).toBe("i18n:errors.emailAlreadyRegistered");
    expect(mapApiError("Invalid email or password", t)).toBe("i18n:errors.invalidCredentials");
    expect(mapApiError("This email already belongs to a member of this company", t)).toBe(
      "i18n:settings.members.invite.alreadyMember",
    );
    expect(mapApiError("A pending invite already exists for this email", t)).toBe(
      "i18n:settings.members.invite.alreadyPending",
    );
    expect(mapApiError("A pending proposal already exists for this product code", t)).toBe(
      "i18n:settings.products.alreadyPending",
    );
    expect(mapApiError("A product with this product code already exists", t)).toBe(
      "i18n:settings.products.fields.skuConflict",
    );
    expect(mapApiError("image_required", t)).toBe("i18n:preview.error.imageRequired");
    expect(mapApiError("social_account_not_connected", t)).toBe("i18n:preview.error.notConnected");
    expect(mapApiError("meta_oauth_not_professional", t)).toBe(
      "i18n:settings.instagram.oauthNotProfessional",
    );
    expect(mapApiError("meta_oauth_missing_publish", t)).toBe(
      "i18n:settings.instagram.oauthMissingPublish",
    );
  });

  it("maps Request failed (N) to errors.requestFailed with status", () => {
    expect(mapApiError("Request failed (404)", t)).toBe("errors.requestFailed:404");
  });

  it("passthroughs unknown messages", () => {
    expect(mapApiError("Something unexpected", t)).toBe("Something unexpected");
  });
});
