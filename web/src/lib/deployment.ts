/**
 * Build-time deployment mode (ADR 0023).
 *
 * `import.meta.env.VITE_DEPLOYMENT_MODE` is substituted by Vite at `vite build`
 * time, so the mode is baked into the bundle and can never change at runtime.
 * On-prem images build with the default (`onprem`); cloud builds set
 * `VITE_DEPLOYMENT_MODE=cloud`. Unknown / unset values fall back to `onprem`
 * (self-hosted safe default). The backend exposes the same flag via
 * `GET /api/meta` — treat that as the source of truth when they disagree.
 */
export type DeploymentMode = "cloud" | "onprem";

export function resolveDeploymentMode(raw: string | undefined): DeploymentMode {
  return raw === "cloud" ? "cloud" : "onprem";
}

export const DEPLOYMENT_MODE: DeploymentMode = resolveDeploymentMode(
  import.meta.env.VITE_DEPLOYMENT_MODE,
);

export const IS_CLOUD = DEPLOYMENT_MODE === "cloud";
export const IS_ONPREM = DEPLOYMENT_MODE === "onprem";
