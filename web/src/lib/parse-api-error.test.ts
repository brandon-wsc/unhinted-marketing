import { describe, expect, it, vi } from "vitest";
import { parseApiErrorBody, parseApiErrorResponse } from "@/lib/parse-api-error";

describe("parseApiErrorBody", () => {
  it("returns detail string when present", () => {
    expect(parseApiErrorBody({ detail: "Email already registered" }, 400)).toBe(
      "Email already registered",
    );
  });

  it("maps password too short validation item", () => {
    expect(
      parseApiErrorBody(
        {
          detail: [
            {
              type: "string_too_short",
              loc: ["body", "password"],
              msg: "String should have at least 8 characters",
            },
          ],
        },
        422,
      ),
    ).toBe("Password must be at least 8 characters");
  });

  it("maps invalid email validation item", () => {
    expect(
      parseApiErrorBody(
        {
          detail: [
            {
              type: "value_error",
              loc: ["body", "email"],
              msg: "value is not a valid email address",
            },
          ],
        },
        422,
      ),
    ).toBe("Invalid email address");
  });

  it("falls back to Request failed (N) when detail is missing", () => {
    expect(parseApiErrorBody({}, 503)).toBe("Request failed (503)");
    expect(parseApiErrorBody({ detail: [] }, 500)).toBe("Request failed (500)");
  });

  it("returns raw msg for unrecognized validation items", () => {
    expect(
      parseApiErrorBody(
        {
          detail: [
            {
              type: "missing",
              loc: ["body", "display_name"],
              msg: "Field required",
            },
          ],
        },
        422,
      ),
    ).toBe("Field required");
  });
});

describe("parseApiErrorResponse", () => {
  it("parses JSON body via parseApiErrorBody", async () => {
    const res = {
      status: 400,
      json: vi.fn().mockResolvedValue({ detail: "Invalid email or password" }),
    } as unknown as Response;

    await expect(parseApiErrorResponse(res)).resolves.toBe("Invalid email or password");
  });

  it("falls back when JSON is malformed", async () => {
    const res = {
      status: 502,
      json: vi.fn().mockRejectedValue(new SyntaxError("Unexpected token")),
    } as unknown as Response;

    await expect(parseApiErrorResponse(res)).resolves.toBe("Request failed (502)");
  });
});
