const STORAGE_PREFIX = "unhinted-session:";

export function rememberedSessionKey(companyId: string): string {
  return `${STORAGE_PREFIX}${companyId}`;
}

export function getRememberedSessionId(companyId: string | undefined): string | null {
  if (!companyId || typeof localStorage === "undefined") return null;
  try {
    return localStorage.getItem(rememberedSessionKey(companyId));
  } catch {
    return null;
  }
}

export function setRememberedSessionId(
  companyId: string | undefined,
  sessionId: string | null,
): void {
  if (!companyId || typeof localStorage === "undefined") return;
  try {
    const key = rememberedSessionKey(companyId);
    if (!sessionId) localStorage.removeItem(key);
    else localStorage.setItem(key, sessionId);
  } catch {
    // ignore quota / private mode
  }
}
