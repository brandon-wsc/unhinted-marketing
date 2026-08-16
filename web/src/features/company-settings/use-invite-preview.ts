import { useEffect, useState } from "react";
import { apiGetInvitePreview, type OrgInvitePreview } from "@/features/company-settings/api";

export type InvitePreviewStatus = "idle" | "loading" | "ok" | "invalid";

export function useInvitePreview(token: string | null | undefined): {
  preview: OrgInvitePreview | null;
  status: InvitePreviewStatus;
} {
  const [preview, setPreview] = useState<OrgInvitePreview | null>(null);
  const [status, setStatus] = useState<InvitePreviewStatus>(token ? "loading" : "idle");

  useEffect(() => {
    if (!token) {
      setPreview(null);
      setStatus("idle");
      return;
    }

    const ac = new AbortController();
    setStatus("loading");
    apiGetInvitePreview(token)
      .then((data) => {
        if (ac.signal.aborted) return;
        setPreview(data);
        setStatus("ok");
      })
      .catch(() => {
        if (ac.signal.aborted) return;
        setPreview(null);
        setStatus("invalid");
      });
    return () => ac.abort();
  }, [token]);

  return { preview, status };
}
