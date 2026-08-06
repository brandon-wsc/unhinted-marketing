export type RememberedUser = {
  email: string;
  displayName: string;
  organizationName: string;
};

const STORAGE_KEY = "unhinted-remembered-user";

export function getRememberedUser(): RememberedUser | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<RememberedUser>;
    if (typeof parsed.email !== "string" || !parsed.email) return null;
    return {
      email: parsed.email,
      displayName: typeof parsed.displayName === "string" ? parsed.displayName : "",
      organizationName: typeof parsed.organizationName === "string" ? parsed.organizationName : "",
    };
  } catch {
    return null;
  }
}

export function setRememberedUser(user: RememberedUser): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(user));
}

export function rememberFromAuthUser(user: {
  email: string;
  display_name: string;
  organizations: Array<{ name: string }>;
}): void {
  setRememberedUser({
    email: user.email,
    displayName: user.display_name,
    organizationName: user.organizations[0]?.name ?? "",
  });
}

export function patchRememberedUser(patch: Partial<RememberedUser>): void {
  const current = getRememberedUser() ?? { email: "", displayName: "", organizationName: "" };
  setRememberedUser({ ...current, ...patch });
}
