/** Extract `/invite/:token` from a safe internal `?next=` path. */

const INVITE_PATH = /^\/invite\/([^/?#]+)/;

export function inviteTokenFromPath(path: string | null | undefined): string | null {
  if (!path) return null;
  const match = path.match(INVITE_PATH);
  return match?.[1] ?? null;
}
