import type {
  ByokCapability,
  ByokCapabilitySource,
  ByokListedModel,
  ByokProviderType,
  ByokRoutingSlot,
  ByokRoutingSlotName,
  ByokRoutingUpdate,
} from "@/features/company-settings/api";

const IMAGE_MARKERS = [
  "dall-e",
  "dalle",
  "seedream",
  "flux",
  "imagen",
  "flash-image",
  "pro-image",
  "image-preview",
  "image-generation",
] as const;

export const PLATFORM_SLOT_VALUE = "__platform__";

export const BYOK_PROVIDER_TYPES: ByokProviderType[] = [
  "openai",
  "anthropic",
  "openai_compatible",
  "gemini",
  "vertex_ai",
];

export type ByokKeyFormValue = {
  label: string;
  providerType: ByokProviderType;
  apiKey: string;
  apiBase: string;
};

export const EMPTY_BYOK_KEY_FORM: ByokKeyFormValue = {
  label: "",
  providerType: "openai",
  apiKey: "",
  apiBase: "",
};

export type ByokKeyFormError = "labelRequired" | "keyRequired" | "apiBaseRequired";

export function validateByokKeyForm(
  value: ByokKeyFormValue,
  opts: { requireKey: boolean },
): ByokKeyFormError | null {
  if (!value.label.trim()) return "labelRequired";
  if (opts.requireKey && !value.apiKey.trim()) return "keyRequired";
  if (value.providerType === "openai_compatible" && !value.apiBase.trim()) {
    return "apiBaseRequired";
  }
  return null;
}

export function inferByokCapability(modelId: string): ByokCapability {
  const lowered = modelId.toLowerCase();
  if (IMAGE_MARKERS.some((marker) => lowered.includes(marker))) return "image";
  if (lowered.includes("-image") || lowered.endsWith("image")) return "image";
  return "chat";
}

export function capabilityFromListedModel(
  modelId: string,
  listed: ByokListedModel | undefined,
): { capability: ByokCapability; source: ByokCapabilitySource } {
  if (listed?.capability === "chat" || listed?.capability === "image") {
    return {
      capability: listed.capability,
      source: listed.capability_source ?? "provider_metadata",
    };
  }
  return { capability: inferByokCapability(modelId), source: "inferred" };
}

export function isByokPending(row: {
  last_verified_at: string | null;
  last_error_kind: string | null;
}): boolean {
  return row.last_verified_at == null && row.last_error_kind == null;
}

export function routingToUpdate(slots: ByokRoutingSlot[]): ByokRoutingUpdate {
  const bySlot = Object.fromEntries(slots.map((item) => [item.slot, item]));
  const idFor = (slot: ByokRoutingSlotName): string | null => {
    const item = bySlot[slot];
    return item?.source === "org" ? item.registry_id : null;
  };
  return {
    cheap_model_id: idFor("cheap"),
    medium_model_id: idFor("medium"),
    strong_model_id: idFor("strong"),
    image_model_id: idFor("image"),
  };
}

export function slotUpdateField(slot: ByokRoutingSlotName): keyof ByokRoutingUpdate {
  if (slot === "cheap") return "cheap_model_id";
  if (slot === "medium") return "medium_model_id";
  if (slot === "strong") return "strong_model_id";
  return "image_model_id";
}
