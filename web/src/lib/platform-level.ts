// Numeric ladder mirrors internal/auth/roles.py (ADR 0005).
export const PLATFORM_LEVEL_ADMIN = 6;
export const PLATFORM_LEVEL_SUPERADMIN = 9;

export function isAdmin(platformLevel: number | undefined): boolean {
  return (platformLevel ?? 0) >= PLATFORM_LEVEL_ADMIN;
}

export function isSuperAdmin(platformLevel: number | undefined): boolean {
  return (platformLevel ?? 0) >= PLATFORM_LEVEL_SUPERADMIN;
}
