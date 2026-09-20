import { fetchWithAuth } from "@/context/auth-context";
import type { TokenResponse } from "@/lib/api";
import { API_BASE } from "@/lib/api-base";
import { parseApiErrorResponse } from "@/lib/parse-api-error";

export type DeploymentMode = "cloud" | "onprem";

export type SetupStatus = {
  deployment_mode: DeploymentMode;
  setup_required: boolean;
  web_base_url: string;
};

export type SetupEmailBackend = "link" | "smtp" | "console";

export type SetupEmailConfig = {
  backend: SetupEmailBackend;
  email_from?: string;
  smtp_host?: string;
  smtp_port?: number;
  smtp_user?: string;
  smtp_password?: string;
  smtp_tls?: boolean;
};

export type SetupRequestBody = {
  email: string;
  password: string;
  display_name: string;
  organization_name?: string;
  web_base_url?: string;
  email_config?: SetupEmailConfig;
};

export type MetaOAuthMode = "byo" | "relay";

export type InstanceSettings = {
  web_base_url: string;
  email_backend: SetupEmailBackend;
  email_from: string;
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password_last4: string | null;
  smtp_tls: boolean;
  meta_app_id: string;
  meta_app_secret_last4: string | null;
  meta_oauth_mode: MetaOAuthMode;
  meta_oauth_callback_url: string | null;
  meta_oauth_relay_url: string;
  meta_oauth_instance_id: string;
  setup_completed: boolean;
};

export type InstanceSettingsUpdate = {
  web_base_url?: string;
  email_config?: SetupEmailConfig;
  meta_app_id?: string;
  meta_app_secret?: string;
  meta_oauth_mode?: MetaOAuthMode;
  meta_oauth_relay_url?: string;
};

export async function apiGetSetupStatus(): Promise<SetupStatus> {
  const res = await fetch(`${API_BASE}/setup/status`, { credentials: "include" });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiRunSetup(body: SetupRequestBody): Promise<TokenResponse> {
  const res = await fetch(`${API_BASE}/setup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiGetInstanceSettings(
  accessToken: string | null,
): Promise<InstanceSettings> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/instance/settings`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiPutInstanceSettings(
  accessToken: string | null,
  body: InstanceSettingsUpdate,
): Promise<InstanceSettings> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/instance/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}
