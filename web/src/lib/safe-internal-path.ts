/** Allow only same-origin relative paths (login/register `?next=`). */

export function safeInternalPath(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const path = raw.trim();
  if (!path.startsWith("/") || path.startsWith("//") || path.startsWith("/\\")) return null;
  if (path.includes("://") || path.includes("\\")) return null;
  return path;
}
