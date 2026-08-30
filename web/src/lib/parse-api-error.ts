type ValidationErrorItem = {
  type: string;
  loc: (string | number)[];
  msg: string;
};

type ApiErrorBody = {
  detail?: string | ValidationErrorItem[] | { message?: string };
};

function fieldFromLoc(loc: (string | number)[]): string | undefined {
  const parts = loc.filter((part): part is string => typeof part === "string" && part !== "body");
  return parts.at(-1);
}

function validationErrorToMessage(item: ValidationErrorItem): string {
  const field = fieldFromLoc(item.loc);

  if (field === "password" && item.type === "string_too_short") {
    return "Password must be at least 8 characters";
  }

  if (field === "email" && item.type === "value_error") {
    return "Invalid email address";
  }

  return item.msg;
}

export function parseApiErrorBody(body: unknown, status: number): string {
  const parsed = body as ApiErrorBody;

  if (typeof parsed.detail === "string") {
    return parsed.detail;
  }

  if (Array.isArray(parsed.detail) && parsed.detail.length > 0) {
    return validationErrorToMessage(parsed.detail[0]);
  }

  if (
    parsed.detail &&
    typeof parsed.detail === "object" &&
    "message" in parsed.detail &&
    typeof parsed.detail.message === "string"
  ) {
    return parsed.detail.message;
  }

  return `Request failed (${status})`;
}

export type ProductSkuConflict = {
  existing: { id: string; name: string; sku: string };
  suggested_sku: string;
};

export function parseSkuConflict(body: unknown): ProductSkuConflict | null {
  if (!body || typeof body !== "object") return null;
  const detail = "detail" in body ? (body as { detail: unknown }).detail : body;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const record = detail as Record<string, unknown>;
  if (record.code !== "sku_taken") return null;
  const existing = record.existing;
  const suggested = record.suggested_sku;
  if (!existing || typeof existing !== "object" || typeof suggested !== "string") return null;
  const row = existing as Record<string, unknown>;
  if (typeof row.id !== "string" || typeof row.name !== "string" || typeof row.sku !== "string") {
    return null;
  }
  return {
    existing: { id: row.id, name: row.name, sku: row.sku },
    suggested_sku: suggested,
  };
}

export type ByokRoutingSlotName = "cheap" | "medium" | "strong" | "image";

export type ByokDependentModel = {
  id: string;
  model_id: string;
  slots: ByokRoutingSlotName[];
};

export type ByokHasDependents = {
  models: ByokDependentModel[];
  slots: ByokRoutingSlotName[];
};

const ROUTING_SLOT_NAMES = new Set<string>(["cheap", "medium", "strong", "image"]);

function isRoutingSlotName(value: unknown): value is ByokRoutingSlotName {
  return typeof value === "string" && ROUTING_SLOT_NAMES.has(value);
}

export function parseHasDependents(body: unknown): ByokHasDependents | null {
  if (!body || typeof body !== "object") return null;
  const detail = "detail" in body ? (body as { detail: unknown }).detail : body;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const record = detail as Record<string, unknown>;
  if (record.code !== "has_dependents") return null;
  const models: ByokDependentModel[] = [];
  if (Array.isArray(record.models)) {
    for (const item of record.models) {
      if (!item || typeof item !== "object") continue;
      const row = item as Record<string, unknown>;
      if (typeof row.id !== "string" || typeof row.model_id !== "string") continue;
      const slots = Array.isArray(row.slots) ? row.slots.filter(isRoutingSlotName) : [];
      models.push({ id: row.id, model_id: row.model_id, slots });
    }
  }
  const slots = Array.isArray(record.slots) ? record.slots.filter(isRoutingSlotName) : [];
  return { models, slots };
}

export async function parseApiErrorResponse(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return parseApiErrorBody(body, res.status);
  } catch {
    return `Request failed (${res.status})`;
  }
}
