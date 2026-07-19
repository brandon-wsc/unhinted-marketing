type ValidationErrorItem = {
  type: string;
  loc: (string | number)[];
  msg: string;
};

type ApiErrorBody = {
  detail?: string | ValidationErrorItem[];
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

  return `Request failed (${status})`;
}

export async function parseApiErrorResponse(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return parseApiErrorBody(body, res.status);
  } catch {
    return `Request failed (${res.status})`;
  }
}
