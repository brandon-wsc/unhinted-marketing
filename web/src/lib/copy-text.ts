/**
 * Copy text to the clipboard.
 *
 * `navigator.clipboard` is secure-context only — it is `undefined` over plain
 * HTTP (e.g. opening the app via a LAN IP). Fall back to a hidden textarea +
 * `document.execCommand("copy")` so copy still works there. Also falls back
 * when `writeText` rejects (denied permission, unfocused document).
 */
export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to the textarea path.
    }
  }
  return legacyCopyText(text);
}

function legacyCopyText(text: string): boolean {
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.top = "0";
  area.style.left = "0";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.focus();
  area.select();
  area.setSelectionRange(0, text.length); // iOS Safari needs an explicit range.
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    area.remove();
  }
}
