import { describe, expect, it } from "vitest";
import { buildLlmCallQuery } from "@/features/admin/api";

describe("buildLlmCallQuery", () => {
  it("builds pagination-only query by default", () => {
    expect(buildLlmCallQuery({}, 50, 0)).toBe("limit=50&offset=0");
  });

  it("includes node, status and fallback filters", () => {
    const query = buildLlmCallQuery(
      { node: " reviewer ", status: "provider_error", fallbackOnly: true },
      50,
      100,
    );
    expect(query).toBe(
      "node=reviewer&status=provider_error&fallback_used=true&limit=50&offset=100",
    );
  });

  it("skips empty node and undefined filters", () => {
    const query = buildLlmCallQuery({ node: "   ", status: "", fallbackOnly: false }, 10, 5);
    expect(query).toBe("limit=10&offset=5");
  });
});
