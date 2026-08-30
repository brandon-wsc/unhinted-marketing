import type {
  ByokCapability,
  ByokCapabilitySource,
  ByokListedModel,
  ByokRoutingSlot,
  ByokRoutingSlotName,
  ByokRoutingUpdate,
} from "@/features/company-settings/api";

const IMAGE_MARKERS = ["dall-e", "dalle", "seedream", "flux", "imagen"] as const;

export const PLATFORM_SLOT_VALUE = "__platform__";
export const NEW_PROVIDER_VALUE = "__new__";

export function inferByokCapability(modelId: string): ByokCapability {
  const lowered = modelId.toLowerCase();
  if (IMAGE_MARKERS.some((marker) => lowered.includes(marker))) return "image";
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
