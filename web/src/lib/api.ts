import { API_BASE } from "@/lib/api-base";
import { parseApiErrorResponse } from "@/lib/parse-api-error";

export type Organization = {
  id: string;
  name: string;
  slug: string;
  role: string;
};

export type User = {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  platform_level: number;
  created_at: string;
  organizations: Organization[];
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
};

export async function apiRegister(input: {
  email: string;
  password: string;
  display_name: string;
  organization_name?: string;
  turnstile_token?: string;
}): Promise<TokenResponse> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiLogin(input: {
  email: string;
  password: string;
  turnstile_token?: string;
}): Promise<TokenResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiRefresh(): Promise<TokenResponse> {
  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiLogout(): Promise<void> {
  await fetch(`${API_BASE}/auth/logout`, { method: "POST", credentials: "include" });
}

export async function apiMe(accessToken: string): Promise<User> {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    credentials: "include",
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}
