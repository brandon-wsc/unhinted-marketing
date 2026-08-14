import { fetchWithAuth } from "@/context/auth-context";
import { API_BASE } from "@/lib/api-base";
import { parseApiErrorResponse } from "@/lib/parse-api-error";

export type CompanyVoiceSettings = {
  company_id: string;
  roast_level: number;
  locale: string;
  forbidden_phrases: string[];
  tone_notes: string;
  exemplar_captions: string[];
  can_edit: boolean;
};

export type CompanyVoiceUpdate = {
  roast_level: number;
  locale: string;
  forbidden_phrases: string[];
  tone_notes: string;
  exemplar_captions: string[];
};

export type ExemplarPromoteResponse = {
  company_id: string;
  exemplar_captions: string[];
  added: boolean;
};

export type ProductScope = "org" | "user";

export type ProductItem = {
  id: string;
  sku: string;
  name: string;
  status: string;
  owner_scope: ProductScope;
  covered_by_company: boolean;
  profile: Record<string, string>;
  updated_at: string;
};

export type ProductListResponse = {
  company_id: string;
  scope: ProductScope;
  items: ProductItem[];
  can_edit: boolean;
};

export type ProductImportResponse = {
  imported: number;
  updated: number;
  skipped: number;
  errors: string[];
};

export async function apiGetCompanyVoice(
  accessToken: string | null,
  companyId: string,
): Promise<CompanyVoiceSettings> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/companies/${companyId}/voice`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiPatchCompanyVoice(
  accessToken: string | null,
  companyId: string,
  body: CompanyVoiceUpdate,
): Promise<CompanyVoiceSettings> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/companies/${companyId}/voice`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiPromoteVoiceExemplar(
  accessToken: string | null,
  companyId: string,
  caption: string,
): Promise<ExemplarPromoteResponse> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/companies/${companyId}/voice/exemplars`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ caption }),
    },
  );
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiListProducts(
  accessToken: string | null,
  companyId: string,
  scope: ProductScope,
): Promise<ProductListResponse> {
  const qs = new URLSearchParams({ scope });
  const res = await fetchWithAuth(accessToken, `${API_BASE}/companies/${companyId}/products?${qs}`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiImportProducts(
  accessToken: string | null,
  companyId: string,
  scope: ProductScope,
  file: File,
): Promise<ProductImportResponse> {
  const qs = new URLSearchParams({ scope });
  const body = new FormData();
  body.append("file", file);
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/companies/${companyId}/products/import?${qs}`,
    { method: "POST", body },
  );
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiCreateProduct(
  accessToken: string | null,
  companyId: string,
  scope: ProductScope,
  input: { name: string; sku: string; notes?: string },
): Promise<ProductItem> {
  const qs = new URLSearchParams({ scope });
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/companies/${companyId}/products?${qs}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiArchiveProduct(
  accessToken: string | null,
  companyId: string,
  productId: string,
): Promise<ProductItem> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/companies/${companyId}/products/${productId}/archive`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export type CompanyMemberRole = "owner" | "admin" | "member";
export type InviteRole = "admin" | "member";

export type CompanyMember = {
  user_id: string;
  email: string;
  display_name: string;
  role: CompanyMemberRole;
  joined_at: string;
};

export type CompanySummary = {
  id: string;
  name: string;
  slug: string;
};

export type OrgInviteItem = {
  id: string;
  email: string;
  role: InviteRole;
  invite_url: string | null;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  created_at: string;
};

export type OrgInviteAcceptResponse = {
  company_id: string;
  role: InviteRole;
};

export class ApiStatusError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiStatusError";
    this.status = status;
  }
}

async function throwApiError(res: Response): Promise<never> {
  throw new ApiStatusError(res.status, await parseApiErrorResponse(res));
}

export async function apiPatchCompanyName(
  accessToken: string | null,
  companyId: string,
  name: string,
): Promise<CompanySummary> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/companies/${companyId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function apiListMembers(
  accessToken: string | null,
  companyId: string,
): Promise<{ company_id: string; items: CompanyMember[] }> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/companies/${companyId}/members`);
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function apiPatchMemberRole(
  accessToken: string | null,
  companyId: string,
  userId: string,
  role: InviteRole,
): Promise<CompanyMember> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/companies/${companyId}/members/${userId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    },
  );
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function apiRemoveMember(
  accessToken: string | null,
  companyId: string,
  userId: string,
): Promise<void> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/companies/${companyId}/members/${userId}`,
    { method: "DELETE" },
  );
  if (!res.ok) await throwApiError(res);
}

export async function apiListInvites(
  accessToken: string | null,
  companyId: string,
): Promise<{ company_id: string; items: OrgInviteItem[] }> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/companies/${companyId}/invites`);
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function apiCreateInvite(
  accessToken: string | null,
  companyId: string,
  body: { email: string; role: InviteRole },
): Promise<OrgInviteItem> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/companies/${companyId}/invites`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function apiRevokeInvite(
  accessToken: string | null,
  companyId: string,
  inviteId: string,
): Promise<void> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/companies/${companyId}/invites/${inviteId}`,
    { method: "DELETE" },
  );
  if (!res.ok) await throwApiError(res);
}

export async function apiAcceptInvite(
  accessToken: string | null,
  token: string,
): Promise<OrgInviteAcceptResponse> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/invites/${token}/accept`, {
    method: "POST",
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}
