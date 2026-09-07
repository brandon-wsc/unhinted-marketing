import { describe, expect, it } from "vitest";
import { DEPLOYMENT_MODE, IS_CLOUD, IS_ONPREM, resolveDeploymentMode } from "@/lib/deployment";

describe("resolveDeploymentMode", () => {
  it("falls back to onprem when unset, empty, or unknown", () => {
    expect(resolveDeploymentMode(undefined)).toBe("onprem");
    expect(resolveDeploymentMode("")).toBe("onprem");
    expect(resolveDeploymentMode("edge")).toBe("onprem");
  });

  it("accepts cloud and onprem", () => {
    expect(resolveDeploymentMode("cloud")).toBe("cloud");
    expect(resolveDeploymentMode("onprem")).toBe("onprem");
  });
});

describe("DEPLOYMENT_MODE", () => {
  it("stays consistent with the IS_CLOUD / IS_ONPREM helpers", () => {
    expect(IS_CLOUD).toBe(DEPLOYMENT_MODE === "cloud");
    expect(IS_ONPREM).toBe(DEPLOYMENT_MODE === "onprem");
  });
});
