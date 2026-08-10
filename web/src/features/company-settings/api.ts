import { fetchWithAuth } from "@/context/auth-context";
import { API_BASE } from "@/lib/api-base";
import { parseApiErrorResponse } from "@/lib/parse-api-error";

export type CompanyVoiceSettings = {
  company_id: string;
  roast_level: number;
  locale: string;
  forbidden_phrases: string[];
  tone_notes: string;
  can_edit: boolean;
};

export type CompanyVoiceUpdate = {
  roast_level: number;
  locale: string;
  forbidden_phrases: string[];
  tone_notes: string;
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
