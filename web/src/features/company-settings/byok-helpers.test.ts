import { describe, expect, it } from "vitest";
import {
  capabilityFromListedModel,
  inferByokCapability,
  isByokPending,
  routingToUpdate,
  slotUpdateField,
} from "@/features/company-settings/byok-helpers";

describe("inferByokCapability", () => {
  it("maps image markers", () => {
    expect(inferByokCapability("dall-e-3")).toBe("image");
    expect(inferByokCapability("seedream-4.0")).toBe("image");
    expect(inferByokCapability("flux-schnell")).toBe("image");
    expect(inferByokCapability("imagen-3")).toBe("image");
  });

  it("defaults to chat", () => {
    expect(inferByokCapability("gpt-4o")).toBe("chat");
    expect(inferByokCapability("deepseek-v4-flash")).toBe("chat");
  });
});

describe("capabilityFromListedModel", () => {
  it("prefers provider metadata", () => {
    expect(
      capabilityFromListedModel("gpt-4o", {
        id: "gpt-4o",
        capability: "chat",
        capability_source: "provider_metadata",
      }),
    ).toEqual({ capability: "chat", source: "provider_metadata" });
  });

  it("infers when the catalog has no capability", () => {
    expect(capabilityFromListedModel("seedream", { id: "seedream" })).toEqual({
      capability: "image",
      source: "inferred",
    });
  });
});

describe("isByokPending", () => {
  it("is pending only with neither stamp nor error", () => {
    expect(isByokPending({ last_verified_at: null, last_error_kind: null })).toBe(true);
    expect(isByokPending({ last_verified_at: "2026-01-01T00:00:00Z", last_error_kind: null })).toBe(
      false,
    );
    expect(isByokPending({ last_verified_at: null, last_error_kind: "auth" })).toBe(false);
  });
});

describe("routingToUpdate", () => {
  it("sends org registry ids and nulls env slots", () => {
    expect(
      routingToUpdate([
        { slot: "cheap", source: "org", registry_id: "c1", model_id: "flash" },
        { slot: "medium", source: "env", registry_id: null, model_id: "gpt-4o-mini" },
        { slot: "strong", source: "org", registry_id: "s1", model_id: "fable-5" },
        { slot: "image", source: "env", registry_id: null, model_id: null },
      ]),
    ).toEqual({
      cheap_model_id: "c1",
      medium_model_id: null,
      strong_model_id: "s1",
      image_model_id: null,
    });
  });
});

describe("slotUpdateField", () => {
  it("maps slot names to PUT fields", () => {
    expect(slotUpdateField("cheap")).toBe("cheap_model_id");
    expect(slotUpdateField("image")).toBe("image_model_id");
  });
});
