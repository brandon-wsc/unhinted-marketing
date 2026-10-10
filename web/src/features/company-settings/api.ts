import { fetchWithAuth } from "@/context/auth-context";
import { API_BASE } from "@/lib/api-base";
import { apiFetch, apiJson } from "@/lib/api-fetch";
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

async function productWriteErrorMapper(res: Response): Promise<Error> {
  const body: unknown = await res.json().catch(() => null);
  const conflict = parseSkuConflict(body);
  if (conflict) return new ProductSkuConflictError(conflict);
  return new Error(parseApiErrorBody(body ?? {}, res.status));
}

export async function apiGetCompanyVoice(
  accessToken: string | null,
  companyId: string,
): Promise<CompanyVoiceSettings> {
  return apiJson<CompanyVoiceSettings>(accessToken, `${API_BASE}/companies/${companyId}/voice`);
}

export async function apiPatchCompanyVoice(
  accessToken: string | null,
  companyId: string,
  body: CompanyVoiceUpdate,
): Promise<CompanyVoiceSettings> {
  return apiJson<CompanyVoiceSettings>(accessToken, `${API_BASE}/companies/${companyId}/voice`, {
    method: "PATCH",
    json: body,
  });
}

export async function apiPromoteVoiceExemplar(
  accessToken: string | null,
  companyId: string,
  caption: string,
): Promise<ExemplarPromoteResponse> {
  return apiJson<ExemplarPromoteResponse>(
    accessToken,
    `${API_BASE}/companies/${companyId}/voice/exemplars`,
    { method: "POST", json: { caption } },
  );
}

export async function apiListProducts(
  accessToken: string | null,
  companyId: string,
  scope: ProductScope,
): Promise<ProductListResponse> {
  const qs = new URLSearchParams({ scope });
  return apiJson<ProductListResponse>(
    accessToken,
    `${API_BASE}/companies/${companyId}/products?${qs}`,
  );
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
  return apiJson<ProductImportResponse>(
    accessToken,
    `${API_BASE}/companies/${companyId}/products/import?${qs}`,
    { method: "POST", body },
  );
}

export async function apiCreateProduct(
  accessToken: string | null,
  companyId: string,
  scope: ProductScope,
  input: { name: string; sku: string; notes?: string },
): Promise<ProductItem> {
  const qs = new URLSearchParams({ scope });
  return apiJson<ProductItem>(
    accessToken,
    `${API_BASE}/companies/${companyId}/products?${qs}`,
    { method: "POST", json: input },
    productWriteErrorMapper,
  );
}

export async function apiPatchProduct(
  accessToken: string | null,
  companyId: string,
  productId: string,
  input: { name: string; sku: string; notes?: string },
): Promise<ProductItem> {
  return apiJson<ProductItem>(
    accessToken,
    `${API_BASE}/companies/${companyId}/products/${productId}`,
    { method: "PATCH", json: input },
    productWriteErrorMapper,
  );
}

export async function apiArchiveProduct(
  accessToken: string | null,
  companyId: string,
  productId: string,
): Promise<ProductItem> {
  return apiJson<ProductItem>(
    accessToken,
    `${API_BASE}/companies/${companyId}/products/${productId}/archive`,
    { method: "POST" },
  );
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
  return apiJson<ProductProposalItem>(
    accessToken,
    `${API_BASE}/companies/${companyId}/products/${productId}/propose`,
    { method: "POST" },
  );
}

export async function apiCancelProposal(
  accessToken: string | null,
  companyId: string,
  proposalId: string,
): Promise<ProductProposalItem> {
  return apiJson<ProductProposalItem>(
    accessToken,
    `${API_BASE}/companies/${companyId}/proposals/${proposalId}/cancel`,
    { method: "POST" },
  );
}

export async function apiListProposals(
  accessToken: string | null,
  companyId: string,
): Promise<{ company_id: string; items: ProductProposalItem[] }> {
  return apiJson(accessToken, `${API_BASE}/companies/${companyId}/proposals`);
}

export async function apiApproveProposal(
  accessToken: string | null,
  companyId: string,
  proposalId: string,
): Promise<ProductProposalItem> {
  return apiJson<ProductProposalItem>(
    accessToken,
    `${API_BASE}/companies/${companyId}/proposals/${proposalId}/approve`,
    { method: "POST" },
  );
}

export async function apiRejectProposal(
  accessToken: string | null,
  companyId: string,
  proposalId: string,
): Promise<ProductProposalItem> {
  return apiJson<ProductProposalItem>(
    accessToken,
    `${API_BASE}/companies/${companyId}/proposals/${proposalId}/reject`,
    { method: "POST" },
  );
}

export type CompanyMemberRole = "owner" | "admin" | "member";
export type InviteRole = "admin" | "member";

export type CompanyMember = {
  user_id: string;
  email: string;
  display_name: string;
  role: CompanyMemberRole;
  joined_at: string;
  monthly_token_limit: number | null;
  used_tokens: number;
  used_platform_tokens: number;
  used_byok_tokens: number;
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

const statusErrorMapper = async (res: Response): Promise<Error> =>
  new ApiStatusError(res.status, await parseApiErrorResponse(res));

export async function apiPatchCompanyName(
  accessToken: string | null,
  companyId: string,
  name: string,
): Promise<CompanySummary> {
  return apiJson<CompanySummary>(
    accessToken,
    `${API_BASE}/companies/${companyId}`,
    { method: "PATCH", json: { name } },
    statusErrorMapper,
  );
}

export async function apiListMembers(
  accessToken: string | null,
  companyId: string,
): Promise<{ company_id: string; items: CompanyMember[] }> {
  return apiJson(
    accessToken,
    `${API_BASE}/companies/${companyId}/members`,
    undefined,
    statusErrorMapper,
  );
}

export async function apiPatchMember(
  accessToken: string | null,
  companyId: string,
  userId: string,
  patch: { role?: InviteRole; monthly_token_limit?: number | null },
): Promise<CompanyMember> {
  return apiJson<CompanyMember>(
    accessToken,
    `${API_BASE}/companies/${companyId}/members/${userId}`,
    { method: "PATCH", json: patch },
    statusErrorMapper,
  );
}

export async function apiRemoveMember(
  accessToken: string | null,
  companyId: string,
  userId: string,
): Promise<void> {
  await apiFetch(
    accessToken,
    `${API_BASE}/companies/${companyId}/members/${userId}`,
    { method: "DELETE" },
    statusErrorMapper,
  );
}

export async function apiListInvites(
  accessToken: string | null,
  companyId: string,
): Promise<{ company_id: string; items: OrgInviteItem[] }> {
  return apiJson(
    accessToken,
    `${API_BASE}/companies/${companyId}/invites`,
    undefined,
    statusErrorMapper,
  );
}

export async function apiCreateInvite(
  accessToken: string | null,
  companyId: string,
  body: { email: string; role: InviteRole },
): Promise<OrgInviteItem> {
  return apiJson<OrgInviteItem>(
    accessToken,
    `${API_BASE}/companies/${companyId}/invites`,
    { method: "POST", json: body },
    statusErrorMapper,
  );
}

export async function apiRevokeInvite(
  accessToken: string | null,
  companyId: string,
  inviteId: string,
): Promise<void> {
  await apiFetch(
    accessToken,
    `${API_BASE}/companies/${companyId}/invites/${inviteId}`,
    { method: "DELETE" },
    statusErrorMapper,
  );
}

export async function apiGetInvitePreview(token: string): Promise<OrgInvitePreview> {
  return apiJson<OrgInvitePreview>(
    null,
    `${API_BASE}/invites/${encodeURIComponent(token)}`,
    undefined,
    statusErrorMapper,
  );
}

export async function apiAcceptInvite(
  accessToken: string | null,
  token: string,
): Promise<OrgInviteAcceptResponse> {
  return apiJson<OrgInviteAcceptResponse>(
    accessToken,
    `${API_BASE}/invites/${token}/accept`,
    { method: "POST" },
    statusErrorMapper,
  );
}

export type CompanyGovernanceSettings = {
  company_id: string;
  member_publish_requires_approval: boolean;
  can_edit: boolean;
};

export async function apiGetGovernance(
  accessToken: string | null,
  companyId: string,
): Promise<CompanyGovernanceSettings> {
  return apiJson(
    accessToken,
    `${API_BASE}/companies/${companyId}/governance`,
    undefined,
    statusErrorMapper,
  );
}

export async function apiPatchGovernance(
  accessToken: string | null,
  companyId: string,
  patch: { member_publish_requires_approval: boolean },
): Promise<CompanyGovernanceSettings> {
  return apiJson<CompanyGovernanceSettings>(
    accessToken,
    `${API_BASE}/companies/${companyId}/governance`,
    { method: "PATCH", json: patch },
    statusErrorMapper,
  );
}
export type PublishApprovalMediaItem = {
  id: string;
  url: string | null;
  plan: Record<string, unknown>;
  format: string;
  role: string;
  seq: number;
  status: string;
};

export type PublishApprovalItem = {
  id: string;
  session_id: string;
  user_id: string;
  requested_by_email: string | null;
  requested_by_name: string | null;
  platform: string;
  revision: number;
  draft_copy: { caption: string; hashtags: string[]; cta: string };
  media: PublishApprovalMediaItem[];
  image_url: string | null;
  status: string;
  idempotency_key: string;
  permalink: string | null;
  error_kind: string | null;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by_email: string | null;
};

export async function apiListPublishApprovals(
  accessToken: string | null,
  companyId: string,
): Promise<{ company_id: string; items: PublishApprovalItem[] }> {
  return apiJson(
    accessToken,
    `${API_BASE}/companies/${companyId}/publish-approvals`,
    undefined,
    statusErrorMapper,
  );
}

export async function apiApprovePublishRequest(
  accessToken: string | null,
  companyId: string,
  receiptId: string,
): Promise<PublishApprovalItem> {
  return apiJson<PublishApprovalItem>(
    accessToken,
    `${API_BASE}/companies/${companyId}/publish-approvals/${receiptId}/approve`,
    { method: "POST" },
    statusErrorMapper,
  );
}

export async function apiRejectPublishRequest(
  accessToken: string | null,
  companyId: string,
  receiptId: string,
): Promise<PublishApprovalItem> {
  return apiJson<PublishApprovalItem>(
    accessToken,
    `${API_BASE}/companies/${companyId}/publish-approvals/${receiptId}/reject`,
    { method: "POST" },
    statusErrorMapper,
  );
}

export type ByokProviderType =
  | "openai"
  | "anthropic"
  | "openai_compatible"
  | "gemini"
  | "vertex_ai";
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

async function byokErrorMapper(res: Response): Promise<Error> {
  const body: unknown = await res.json().catch(() => null);
  const conflict = parseHasDependents(body);
  if (res.status === 409 && conflict) return new ByokDependentsError(conflict);
  return new ApiStatusError(res.status, parseApiErrorBody(body ?? {}, res.status));
}

function byokPath(companyId: string, suffix: string): string {
  return `${API_BASE}/companies/${companyId}/byok${suffix}`;
}

export async function apiListByokProviders(
  accessToken: string | null,
  companyId: string,
): Promise<ByokProviderItem[]> {
  const body = await apiJson<{ items: ByokProviderItem[] }>(
    accessToken,
    byokPath(companyId, "/providers"),
    undefined,
    statusErrorMapper,
  );
  return body.items;
}

export async function apiCreateByokProvider(
  accessToken: string | null,
  companyId: string,
  body: ByokProviderCreate,
): Promise<ByokProviderItem> {
  return apiJson<ByokProviderItem>(
    accessToken,
    byokPath(companyId, "/providers"),
    { method: "POST", json: body },
    byokErrorMapper,
  );
}

export async function apiPatchByokProvider(
  accessToken: string | null,
  companyId: string,
  providerId: string,
  body: ByokProviderPatch,
): Promise<ByokProviderItem> {
  return apiJson<ByokProviderItem>(
    accessToken,
    byokPath(companyId, `/providers/${providerId}`),
    { method: "PATCH", json: body },
    byokErrorMapper,
  );
}

export async function apiDeleteByokProvider(
  accessToken: string | null,
  companyId: string,
  providerId: string,
  force = false,
): Promise<void> {
  const suffix = force ? `/providers/${providerId}?force=true` : `/providers/${providerId}`;
  await apiFetch(accessToken, byokPath(companyId, suffix), { method: "DELETE" }, byokErrorMapper);
}

export async function apiTestByokProvider(
  accessToken: string | null,
  companyId: string,
  providerId: string,
): Promise<ByokProbeResult> {
  return apiJson<ByokProbeResult>(
    accessToken,
    byokPath(companyId, `/providers/${providerId}/test`),
    { method: "POST" },
    statusErrorMapper,
  );
}

export async function apiListByokProviderCatalog(
  accessToken: string | null,
  companyId: string,
  providerId: string,
): Promise<ByokModelListProxy> {
  return apiJson<ByokModelListProxy>(
    accessToken,
    byokPath(companyId, `/providers/${providerId}/models`),
    undefined,
    statusErrorMapper,
  );
}

export async function apiListByokModels(
  accessToken: string | null,
  companyId: string,
): Promise<ByokModelItem[]> {
  const body = await apiJson<{ items: ByokModelItem[] }>(
    accessToken,
    byokPath(companyId, "/models"),
    undefined,
    statusErrorMapper,
  );
  return body.items;
}

export async function apiCreateByokModel(
  accessToken: string | null,
  companyId: string,
  body: ByokModelCreate,
): Promise<ByokModelItem> {
  return apiJson<ByokModelItem>(
    accessToken,
    byokPath(companyId, "/models"),
    { method: "POST", json: body },
    byokErrorMapper,
  );
}

export async function apiDeleteByokModel(
  accessToken: string | null,
  companyId: string,
  modelPk: string,
  force = false,
): Promise<void> {
  const suffix = force ? `/models/${modelPk}?force=true` : `/models/${modelPk}`;
  await apiFetch(accessToken, byokPath(companyId, suffix), { method: "DELETE" }, byokErrorMapper);
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
  return apiJson<ByokProbeResult>(
    accessToken,
    byokPath(companyId, suffix),
    { method: "POST" },
    statusErrorMapper,
  );
}

export async function apiGetByokRouting(
  accessToken: string | null,
  companyId: string,
): Promise<ByokRoutingResponse> {
  return apiJson<ByokRoutingResponse>(
    accessToken,
    byokPath(companyId, "/routing"),
    undefined,
    statusErrorMapper,
  );
}

export async function apiPutByokRouting(
  accessToken: string | null,
  companyId: string,
  body: ByokRoutingUpdate,
): Promise<ByokRoutingResponse> {
  return apiJson<ByokRoutingResponse>(
    accessToken,
    byokPath(companyId, "/routing"),
    { method: "PUT", json: body },
    statusErrorMapper,
  );
}

export type SocialAccountItem = {
  id: string;
  company_id: string;
  platform: "instagram";
  ig_user_id: string;
  token_last4: string;
  expires_at: string | null;
  last_verified_at: string | null;
  last_error_kind: string | null;
  created_at: string;
  updated_at: string;
};

export type SocialAccountList = {
  items: SocialAccountItem[];
};

function socialPath(companyId: string, suffix = ""): string {
  return `${API_BASE}/companies/${companyId}/social-accounts${suffix}`;
}

export async function apiListSocialAccounts(
  accessToken: string | null,
  companyId: string,
): Promise<SocialAccountItem[]> {
  const body = await apiJson<SocialAccountList>(
    accessToken,
    socialPath(companyId),
    undefined,
    statusErrorMapper,
  );
  return body.items ?? [];
}

export type SocialAccountUpsertBody = {
  ig_user_id: string;
  access_token: string;
  expires_at?: string | null;
};

export async function apiUpsertSocialAccount(
  accessToken: string | null,
  companyId: string,
  platform: string,
  body: SocialAccountUpsertBody,
): Promise<SocialAccountItem> {
  return apiJson<SocialAccountItem>(
    accessToken,
    socialPath(companyId, `/${platform}`),
    { method: "PUT", json: body },
    statusErrorMapper,
  );
}

export async function apiDisconnectInstagramAccount(
  accessToken: string | null,
  companyId: string,
): Promise<void> {
  // 404 is fine — disconnect is idempotent.
  const res = await fetchWithAuth(accessToken, socialPath(companyId, "/instagram"), {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 404) {
    throw new ApiStatusError(res.status, await parseApiErrorResponse(res));
  }
}

export type SocialOAuthStatus = "not_connected" | "pending" | "connected";

export type SocialOAuthInfo = {
  status: SocialOAuthStatus;
  authorization_url?: string | null;
  poll_url?: string | null;
  configured?: boolean;
  callback_url?: string | null;
  deauthorize_url?: string | null;
  data_deletion_url?: string | null;
  mode?: "byo" | "relay";
};

export async function apiStartInstagramOAuth(
  accessToken: string | null,
  companyId: string,
): Promise<SocialOAuthInfo> {
  return apiJson<SocialOAuthInfo>(
    accessToken,
    socialPath(companyId, "/oauth/start"),
    { method: "POST" },
    statusErrorMapper,
  );
}

export async function apiGetInstagramOAuthStatus(
  accessToken: string | null,
  companyId: string,
): Promise<SocialOAuthInfo> {
  return apiJson<SocialOAuthInfo>(
    accessToken,
    socialPath(companyId, "/oauth/status"),
    undefined,
    statusErrorMapper,
  );
}

export async function apiCancelInstagramOAuth(
  accessToken: string | null,
  companyId: string,
): Promise<SocialOAuthInfo> {
  return apiJson<SocialOAuthInfo>(
    accessToken,
    socialPath(companyId, "/oauth/cancel"),
    { method: "POST" },
    statusErrorMapper,
  );
}

export type StorageBackend = "local" | "s3";

export type StorageMigrationState =
  | "validating"
  | "copying"
  | "verifying"
  | "ready_to_flip"
  | "flipping"
  | "completed"
  | "cleaning"
  | "done"
  | "failed";

export type StorageMigration = {
  id: string;
  state: StorageMigrationState;
  stats: {
    scanned?: number;
    copied?: number;
    skipped?: number;
    bytes?: number;
    orphans?: number;
  };
  error_keys: { key?: string; error?: string }[];
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type StorageConfig = {
  backend: StorageBackend;
  bucket: string | null;
  endpoint_url: string | null;
  region: string;
  public_base_url: string | null;
  access_key: string | null;
  secret_last4: string | null;
  seeded_from_env: boolean;
  dual_write: boolean;
  can_migrate: boolean;
  migration: StorageMigration | null;
};

export type StorageConfigUpdate = {
  bucket: string;
  endpoint_url?: string | null;
  region?: string | null;
  public_base_url?: string | null;
  access_key?: string | null;
  secret_key?: string | null;
};

export type StorageTestResult = {
  ok: boolean;
  error: string | null;
};

function storagePath(companyId: string, suffix = "") {
  return `${API_BASE}/companies/${companyId}/storage${suffix}`;
}

export async function apiGetStorageConfig(
  accessToken: string | null,
  companyId: string,
): Promise<StorageConfig> {
  return apiJson<StorageConfig>(
    accessToken,
    storagePath(companyId, "/config"),
    undefined,
    statusErrorMapper,
  );
}

export async function apiPutStorageConfig(
  accessToken: string | null,
  companyId: string,
  body: StorageConfigUpdate,
): Promise<StorageConfig> {
  return apiJson<StorageConfig>(
    accessToken,
    storagePath(companyId, "/config"),
    { method: "PUT", json: body },
    statusErrorMapper,
  );
}

export async function apiTestStorageConnection(
  accessToken: string | null,
  companyId: string,
  body: StorageConfigUpdate,
): Promise<StorageTestResult> {
  return apiJson<StorageTestResult>(
    accessToken,
    storagePath(companyId, "/test"),
    { method: "POST", json: body },
    statusErrorMapper,
  );
}

export async function apiStartStorageMigration(
  accessToken: string | null,
  companyId: string,
): Promise<StorageMigration> {
  return apiJson<StorageMigration>(
    accessToken,
    storagePath(companyId, "/migrations"),
    { method: "POST" },
    statusErrorMapper,
  );
}

export async function apiFlipStorageMigration(
  accessToken: string | null,
  companyId: string,
  migrationId: string,
): Promise<StorageMigration> {
  return apiJson<StorageMigration>(
    accessToken,
    storagePath(companyId, `/migrations/${migrationId}/flip`),
    { method: "POST" },
    statusErrorMapper,
  );
}

export async function apiRollbackStorageMigration(
  accessToken: string | null,
  companyId: string,
  migrationId: string,
): Promise<StorageMigration> {
  return apiJson<StorageMigration>(
    accessToken,
    storagePath(companyId, `/migrations/${migrationId}/rollback`),
    { method: "POST" },
    statusErrorMapper,
  );
}

export async function apiCleanStorageMigration(
  accessToken: string | null,
  companyId: string,
  migrationId: string,
): Promise<StorageMigration> {
  return apiJson<StorageMigration>(
    accessToken,
    storagePath(companyId, `/migrations/${migrationId}/clean`),
    { method: "POST" },
    statusErrorMapper,
  );
}
