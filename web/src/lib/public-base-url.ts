/**
 * Shape-check an instance base URL for the Instagram publish requirement
 * (ADR 0043 §3): a soft warning, never a block — LAN-only installs that
 * never publish are legitimate. Mirrors `publish_url_reachability` in
 * internal/media/storage.py (minus the unset case — empty fields show the
 * normal hint, not a warning).
 */

const PRIVATE_HOST_SUFFIXES = [".local", ".internal", ".lan", ".home.arpa", ".corp", ".localhost"];

function isPrivateIpv4(host: string): boolean {
  const m = /^(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}$/.exec(host);
  if (!m) return false;
  const a = Number(m[1]);
  const b = Number(m[2]);
  return (
    a === 0 ||
    a === 10 ||
    a === 127 ||
    (a === 100 && b >= 64 && b <= 127) ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168)
  );
}

function isPrivateIpLiteral(host: string): boolean {
  if (isPrivateIpv4(host)) return true;
  if (!host.includes(":")) return false;
  return (
    host === "::1" ||
    host === "::" ||
    host.startsWith("fc") ||
    host.startsWith("fd") ||
    host.startsWith("fe80")
  );
}

export function looksNonPublicBaseUrl(raw: string): boolean {
  const value = raw.trim();
  if (!value) return false;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  const host = url.hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (!host) return false;
  if (isPrivateIpLiteral(host)) return true;
  if (host === "localhost" || PRIVATE_HOST_SUFFIXES.some((s) => host.endsWith(s))) {
    return true;
  }
  if (!host.includes(".")) return true;
  if (url.protocol === "http:") return true;
  return false;
}
