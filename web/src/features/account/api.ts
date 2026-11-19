import { API_BASE } from "@/lib/api-base";

export type InstanceMeta = {
  web_base_url?: string;
};

/** GET /api/meta — public instance meta; missing/unreachable → null. */
export async function fetchInstanceMeta(): Promise<InstanceMeta | null> {
  const res = await fetch(`${API_BASE}/meta`);
  return res.ok ? res.json() : null;
}
