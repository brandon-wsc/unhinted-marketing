import { useCallback, useState } from "react";

/**
 * Per-field validation error map for auth-style forms. `applyFieldErrors`
 * replaces the map and focuses the first invalid control (keyed by element
 * id); `clearFieldError` drops one entry as the user edits.
 */
export function useFieldErrors(): {
  fieldErrors: Record<string, string>;
  setFieldErrors: (errors: Record<string, string>) => void;
  clearFieldError: (id: string) => void;
  /** Apply a fresh error map; returns true when it is empty. */
  applyFieldErrors: (errors: Record<string, string>) => boolean;
} {
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const clearFieldError = useCallback((id: string) => {
    setFieldErrors((prev) => {
      if (!(id in prev)) return prev;
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);

  const applyFieldErrors = useCallback((errors: Record<string, string>) => {
    setFieldErrors(errors);
    const firstId = Object.keys(errors)[0];
    if (firstId) document.getElementById(firstId)?.focus();
    return !firstId;
  }, []);

  return { fieldErrors, setFieldErrors, clearFieldError, applyFieldErrors };
}
