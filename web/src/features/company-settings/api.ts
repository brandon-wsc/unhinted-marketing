import { fetchWithAuth } from "@/context/auth-context";
import { API_BASE } from "@/lib/api-base";
import {
  type ByokHasDependents,
  type ByokRoutingSlotName,
  type ProductSkuConflict,
  parseApiErrorBody,
  parseApiErrorResponse,
  parseHasDependents,
  parseSkuConflict,
} from "@/lib/parse-api-error";

export type { ByokHasDependents, ByokRoutingSlotName } from "@/lib/parse-api-error";

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
  pending_proposal_id?: string | null;
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

export class ProductSkuConflictError extends Error {
  readonly conflict: ProductSkuConflict;
  constructor(conflict: ProductSkuConflict) {
    super("A product with this product code already exists");
    this.name = "ProductSkuConflictError";
    this.conflict = conflict;
  }
}

async function throwProductWriteError(res: Response): Promise<never> {
  const body: unknown = await res.json().catch(() => null);
  const conflict = parseSkuConflict(body);
  if (conflict) throw new ProductSkuConflictError(conflict);
  throw new Error(parseApiErrorBody(body ?? {}, res.status));
}

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
  if (!res.ok) await throwProductWriteError(res);
  return res.json();
}

export async function apiPatchProduct(
  accessToken: string | null,
  companyId: string,
  productId: string,
  input: { name: string; sku: string; notes?: string },
): Promise<ProductItem> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/companies/${companyId}/products/${productId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  if (!res.ok) await throwProductWriteError(res);
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

export type ProposalFieldChange = "added" | "changed" | "removed" | "same";

export type ProductProposalFieldDiff = {
  key: string;
  current: string | null;
  proposed: string | null;
  change: ProposalFieldChange;
};

export type ProductProposalItem = {
  id: string;
  company_id: string;
  sku: string;
  name: string;
  status: "pending" | "approved" | "rejected" | "cancelled";
  proposed_by: string | null;
  proposed_by_email: string | null;
  source_product_id: string | null;
  profile: Record<string, string>;
  current_name: string | null;
  current_profile: Record<string, string>;
  fields: ProductProposalFieldDiff[];
  created_at: string;
  reviewed_at: string | null;
};

export async function apiProposeProduct(
  accessToken: string | null,
  companyId: string,
  productId: string,
): Promise<ProductProposalItem> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/companies/${companyId}/products/${productId}/propose`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiCancelProposal(
  accessToken: string | null,
  companyId: string,
  proposalId: string,
): Promise<ProductProposalItem> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/companies/${companyId}/proposals/${proposalId}/cancel`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiListProposals(
  accessToken: string | null,
  companyId: string,
): Promise<{ company_id: string; items: ProductProposalItem[] }> {
  const res = await fetchWithAuth(accessToken, `${API_BASE}/companies/${companyId}/proposals`);
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiApproveProposal(
  accessToken: string | null,
  companyId: string,
  proposalId: string,
): Promise<ProductProposalItem> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/companies/${companyId}/proposals/${proposalId}/approve`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await parseApiErrorResponse(res));
  return res.json();
}

export async function apiRejectProposal(
  accessToken: string | null,
  companyId: string,
  proposalId: string,
): Promise<ProductProposalItem> {
  const res = await fetchWithAuth(
    accessToken,
    `${API_BASE}/companies/${companyId}/proposals/${proposalId}/reject`,
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

export type OrgInvitePreview = {
  email: string;
  company_name: string;
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

export async function apiGetInvitePreview(token: string): Promise<OrgInvitePreview> {
  const res = await fetch(`${API_BASE}/invites/${encodeURIComponent(token)}`);
  if (!res.ok) await throwApiError(res);
  return res.json();
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

export type ByokProviderType = "openai" | "anthropic" | "openai_compatible";
export type ByokCapability = "chat" | "image";
export type ByokCapabilitySource = "provider_metadata" | "inferred" | "manual";
export type ByokKeySource = "org" | "env";

export type ByokProviderItem = {
  id: string;
  label: string;
  provider_type: ByokProviderType;
  key_last4: string;
  api_base: string | null;
  last_verified_at: string | null;
  last_error_kind: string | null;
  verified: boolean;
  created_at: string;
  updated_at: string;
};

export type ByokProviderCreate = {
  label: string;
  provider_type: ByokProviderType;
  api_key: string;
  api_base?: string | null;
};

export type ByokProviderPatch = {
  label?: string;
  api_key?: string | null;
  api_base?: string | null;
};

export type ByokModelItem = {
  id: string;
  provider_id: string;
  provider_label: string;
  provider_key_last4: string;
  model_id: string;
  capability: ByokCapability;
  capability_source: ByokCapabilitySource;
  last_verified_at: string | null;
  last_error_kind: string | null;
  verified: boolean;
  created_at: string;
  updated_at: string;
};

export type ByokModelCreate = {
  provider_id: string;
  model_id: string;
  capability: ByokCapability;
  capability_source: ByokCapabilitySource;
};

export type ByokListedModel = {
  id: string;
  capability?: ByokCapability | null;
  capability_source?: ByokCapabilitySource | null;
};

export type ByokModelListProxy = {
  fetchable: boolean;
  models: ByokListedModel[];
};

export type ByokProbeResult = {
  ok: boolean;
  error_kind?: string | null;
};

export type ByokRoutingSlot = {
  slot: ByokRoutingSlotName;
  source: ByokKeySource;
  registry_id: string | null;
  model_id: string | null;
};

export type ByokRoutingResponse = {
  slots: ByokRoutingSlot[];
};

export type ByokRoutingUpdate = {
  cheap_model_id: string | null;
  medium_model_id: string | null;
  strong_model_id: string | null;
  image_model_id: string | null;
};

export class ByokDependentsError extends Error {
  readonly conflict: ByokHasDependents;
  constructor(conflict: ByokHasDependents) {
    super("This key or model is still in use");
    this.name = "ByokDependentsError";
    this.conflict = conflict;
  }
}

async function throwByokError(res: Response): Promise<never> {
  const body: unknown = await res.json().catch(() => null);
  const conflict = parseHasDependents(body);
  if (res.status === 409 && conflict) throw new ByokDependentsError(conflict);
  throw new ApiStatusError(res.status, parseApiErrorBody(body ?? {}, res.status));
}

function byokPath(companyId: string, suffix: string): string {
  return `${API_BASE}/companies/${companyId}/byok${suffix}`;
}

export async function apiListByokProviders(
  accessToken: string | null,
  companyId: string,
): Promise<ByokProviderItem[]> {
  const res = await fetchWithAuth(accessToken, byokPath(companyId, "/providers"));
  if (!res.ok) await throwApiError(res);
  const body = (await res.json()) as { items: ByokProviderItem[] };
  return body.items;
}

export async function apiCreateByokProvider(
  accessToken: string | null,
  companyId: string,
  body: ByokProviderCreate,
): Promise<ByokProviderItem> {
  const res = await fetchWithAuth(accessToken, byokPath(companyId, "/providers"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await throwByokError(res);
  return res.json();
}

export async function apiPatchByokProvider(
  accessToken: string | null,
  companyId: string,
  providerId: string,
  body: ByokProviderPatch,
): Promise<ByokProviderItem> {
  const res = await fetchWithAuth(accessToken, byokPath(companyId, `/providers/${providerId}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await throwByokError(res);
  return res.json();
}

export async function apiDeleteByokProvider(
  accessToken: string | null,
  companyId: string,
  providerId: string,
  force = false,
): Promise<void> {
  const suffix = force ? `/providers/${providerId}?force=true` : `/providers/${providerId}`;
  const res = await fetchWithAuth(accessToken, byokPath(companyId, suffix), {
    method: "DELETE",
  });
  if (!res.ok) await throwByokError(res);
}

export async function apiTestByokProvider(
  accessToken: string | null,
  companyId: string,
  providerId: string,
): Promise<ByokProbeResult> {
  const res = await fetchWithAuth(
    accessToken,
    byokPath(companyId, `/providers/${providerId}/test`),
    { method: "POST" },
  );
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function apiListByokProviderCatalog(
  accessToken: string | null,
  companyId: string,
  providerId: string,
): Promise<ByokModelListProxy> {
  const res = await fetchWithAuth(
    accessToken,
    byokPath(companyId, `/providers/${providerId}/models`),
  );
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function apiListByokModels(
  accessToken: string | null,
  companyId: string,
): Promise<ByokModelItem[]> {
  const res = await fetchWithAuth(accessToken, byokPath(companyId, "/models"));
  if (!res.ok) await throwApiError(res);
  const body = (await res.json()) as { items: ByokModelItem[] };
  return body.items;
}

export async function apiCreateByokModel(
  accessToken: string | null,
  companyId: string,
  body: ByokModelCreate,
): Promise<ByokModelItem> {
  const res = await fetchWithAuth(accessToken, byokPath(companyId, "/models"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await throwByokError(res);
  return res.json();
}

export async function apiDeleteByokModel(
  accessToken: string | null,
  companyId: string,
  modelPk: string,
  force = false,
): Promise<void> {
  const suffix = force ? `/models/${modelPk}?force=true` : `/models/${modelPk}`;
  const res = await fetchWithAuth(accessToken, byokPath(companyId, suffix), {
    method: "DELETE",
  });
  if (!res.ok) await throwByokError(res);
}

export async function apiTestByokModel(
  accessToken: string | null,
  companyId: string,
  modelPk: string,
  confirmPaid = false,
): Promise<ByokProbeResult> {
  const suffix = confirmPaid
    ? `/models/${modelPk}/test?confirm_paid=true`
    : `/models/${modelPk}/test`;
  const res = await fetchWithAuth(accessToken, byokPath(companyId, suffix), {
    method: "POST",
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function apiGetByokRouting(
  accessToken: string | null,
  companyId: string,
): Promise<ByokRoutingResponse> {
  const res = await fetchWithAuth(accessToken, byokPath(companyId, "/routing"));
  if (!res.ok) await throwApiError(res);
  return res.json();
}

export async function apiPutByokRouting(
  accessToken: string | null,
  companyId: string,
  body: ByokRoutingUpdate,
): Promise<ByokRoutingResponse> {
  const res = await fetchWithAuth(accessToken, byokPath(companyId, "/routing"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await throwApiError(res);
  return res.json();
}
