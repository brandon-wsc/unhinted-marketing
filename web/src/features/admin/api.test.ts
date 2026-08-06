import { describe, expect, it } from "vitest";
import { buildLlmCallQuery, buildNodeStepQuery } from "@/features/admin/api";

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

  it("includes turn and session filters", () => {
    const query = buildLlmCallQuery({ turnId: " t1 ", sessionId: " s1 " }, 10, 0);
    expect(query).toBe("turn_id=t1&session_id=s1&limit=10&offset=0");
  });
});

describe("buildNodeStepQuery", () => {
  it("includes node turn session filters", () => {
    expect(buildNodeStepQuery({ node: "reviewer", turnId: "t1", sessionId: "s1" }, 50, 0)).toBe(
      "node=reviewer&session_id=s1&turn_id=t1&limit=50&offset=0",
    );
  });
});
