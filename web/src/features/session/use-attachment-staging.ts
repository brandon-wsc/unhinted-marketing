import type { Dispatch, SetStateAction } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  apiCreateSession,
  apiDownloadAttachment,
  apiListSessionAttachments,
  apiPostAttachmentTranscript,
  apiSaveAttachment,
  apiUploadSessionAttachment,
} from "./api";
import { OcrAbortError, ocrAttachmentToTranscript } from "./ocr/run";
import { defaultOcrDeps } from "./ocr/runtime";
import { MAX_ATTACHMENTS, newStagedAttachment } from "./session-helpers";
import { setRememberedSessionId } from "./session-storage";
import type { OcrRunState, Session, StagedAttachment } from "./types";

// After a transcript POST lands, a GET already in flight can still report the
// pre-commit needs_ocr — treat that read as stale for this window so it cannot
// regress the row's pending patch and stall the resumed ingest poll (ADR 0048).
const OCR_SUBMITTED_STALE_MS = 30_000;

// ADR 0047 — scratch attachments staged in the composer for the next message.
export function useAttachmentStaging({
  accessToken,
  companyId,
  session,
  sessionIdRef,
  setSession,
  refreshHistory,
}: {
  accessToken: string | null | undefined;
  companyId: string | undefined;
  session: Session | null;
  sessionIdRef: { current: string | null };
  setSession: Dispatch<SetStateAction<Session | null>>;
  refreshHistory: () => void;
}) {
  const [stagedAttachments, setStagedAttachments] = useState<StagedAttachment[]>([]);
  const [ocrProgress, setOcrProgress] = useState<Record<string, OcrRunState>>({});
  const stagedRef = useRef<StagedAttachment[]>([]);
  const ocrRunsRef = useRef(new Map<string, AbortController>());
  // attachmentId → Date.now() of its accepted transcript POST; lets the
  // attachment poll ignore stale needs_ocr reads for a bounded window.
  const ocrSubmittedRef = useRef(new Map<string, number>());
  const attachPollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Staged rows are session-scoped — switching sessions drops them.
  const stagedSessionRef = useRef<string | null>(null);
  stagedRef.current = stagedAttachments;

  const refreshStagedStatuses = useCallback(async () => {
    const sid = sessionIdRef.current;
    if (!accessToken || !sid) return;
    try {
      const list = await apiListSessionAttachments(accessToken, sid);
      const byId = new Map(list.attachments.map((a) => [a.id, a]));
      const next = stagedRef.current.map((s) => {
        const row = s.attachmentId ? byId.get(s.attachmentId) : null;
        if (!row || !s.attachmentId) return s;
        const submittedAt = ocrSubmittedRef.current.get(s.attachmentId);
        if (row.status !== "needs_ocr") {
          ocrSubmittedRef.current.delete(s.attachmentId);
        } else if (submittedAt !== undefined && Date.now() - submittedAt < OCR_SUBMITTED_STALE_MS) {
          return s;
        }
        return { ...s, status: row.status, error: row.error ?? null };
      });
      stagedRef.current = next;
      setStagedAttachments(next);
    } catch {
      /* poll is best-effort */
    }
  }, [accessToken, sessionIdRef]);

  useEffect(() => {
    if (attachPollTimerRef.current) {
      clearTimeout(attachPollTimerRef.current);
      attachPollTimerRef.current = null;
    }
    const needsPoll = stagedAttachments.some(
      (s) => s.attachmentId && (s.status === "pending" || s.status === "ready_lexical"),
    );
    if (!needsPoll) return;
    attachPollTimerRef.current = setTimeout(() => {
      attachPollTimerRef.current = null;
      void refreshStagedStatuses();
    }, 1200);
    return () => {
      if (attachPollTimerRef.current) clearTimeout(attachPollTimerRef.current);
      attachPollTimerRef.current = null;
    };
  }, [stagedAttachments, refreshStagedStatuses]);

  useEffect(() => {
    const id = session?.id ?? null;
    if (stagedSessionRef.current === id) return;
    stagedSessionRef.current = id;
    for (const controller of ocrRunsRef.current.values()) controller.abort();
    ocrSubmittedRef.current.clear();
    stagedRef.current = [];
    setStagedAttachments([]);
  }, [session?.id]);

  const patchStaged = useCallback(
    (localId: string) => (mut: (s: StagedAttachment) => StagedAttachment) => {
      const next = stagedRef.current.map((s) => (s.localId === localId ? mut(s) : s));
      stagedRef.current = next;
      setStagedAttachments(next);
    },
    [],
  );

  const uploadAttachment = useCallback(
    async (file: File): Promise<void> => {
      if (!accessToken || !companyId) return;
      if (stagedRef.current.length >= MAX_ATTACHMENTS) {
        throw new Error("attachment_limit");
      }
      let active = session;
      if (!active) {
        active = await apiCreateSession(accessToken, companyId);
        if (sessionIdRef.current === null || sessionIdRef.current === active.id) {
          sessionIdRef.current = active.id;
          setSession(active);
          setRememberedSessionId(companyId, active.id);
          void refreshHistory();
        }
      }
      const staged = newStagedAttachment(file);
      const patch = patchStaged(staged.localId);
      stagedRef.current = [...stagedRef.current, staged];
      setStagedAttachments(stagedRef.current);
      try {
        const out = await apiUploadSessionAttachment(accessToken, active.id, file);
        patch((s) => ({
          ...s,
          attachmentId: out.id,
          status: out.status,
          error: out.error ?? null,
        }));
      } catch (err) {
        patch((s) => ({
          ...s,
          status: "failed",
          error: err instanceof Error ? err.message : "upload_failed",
        }));
        throw err;
      }
    },
    [accessToken, companyId, session, sessionIdRef, setSession, refreshHistory, patchStaged],
  );

  const unstageAttachment = useCallback((localId: string) => {
    ocrRunsRef.current.get(localId)?.abort();
    const cur = stagedRef.current.find((s) => s.localId === localId);
    if (cur?.attachmentId) ocrSubmittedRef.current.delete(cur.attachmentId);
    const next = stagedRef.current.filter((s) => s.localId !== localId);
    stagedRef.current = next;
    setStagedAttachments(next);
  }, []);

  /** Re-POST the same File for a failed staged row (ADR 0047 §10 — no auto-retry). */
  const retryAttachment = useCallback(
    async (localId: string): Promise<void> => {
      const cur = stagedRef.current.find((s) => s.localId === localId);
      const sid = sessionIdRef.current;
      if (!cur?.file || !accessToken || !sid) return;
      const patch = patchStaged(localId);
      patch((s) => ({ ...s, status: "uploading", error: null }));
      try {
        const out = await apiUploadSessionAttachment(accessToken, sid, cur.file);
        patch((s) => ({
          ...s,
          attachmentId: out.id,
          status: out.status,
          error: out.error ?? null,
        }));
      } catch (err) {
        patch((s) => ({
          ...s,
          status: "failed",
          error: err instanceof Error ? err.message : "upload_failed",
        }));
        throw err;
      }
    },
    [accessToken, sessionIdRef, patchStaged],
  );

  /** Take staged items for the next send; returns them so callers can restore on error. */
  const consumeStagedAttachments = useCallback((): StagedAttachment[] => {
    const cur = stagedRef.current;
    stagedRef.current = [];
    setStagedAttachments([]);
    return cur;
  }, []);

  const restoreStagedAttachments = useCallback((items: StagedAttachment[]) => {
    stagedRef.current = items;
    setStagedAttachments(items);
  }, []);

  const saveAttachment = useCallback(
    async (attachmentId: string) => {
      if (!accessToken) return;
      return apiSaveAttachment(accessToken, attachmentId);
    },
    [accessToken],
  );

  // ADR 0049 — browser OCR for rows parked at needs_ocr: download the bytes,
  // transcribe client-side, POST the transcript, then let the existing ingest
  // poll carry the re-parked row to ready. Park stays the safe state on abort
  // or failure — no auto-retry (0048 §9).
  const setOcrRunState = useCallback((localId: string, state: OcrRunState | null) => {
    setOcrProgress((m) => {
      const next = { ...m };
      if (state) next[localId] = state;
      else delete next[localId];
      return next;
    });
  }, []);

  const ocrAttachment = useCallback(
    async (localId: string): Promise<void> => {
      const cur = stagedRef.current.find((s) => s.localId === localId);
      if (!cur?.attachmentId || cur.status !== "needs_ocr" || !accessToken) return;
      if (ocrRunsRef.current.has(localId)) return;
      const controller = new AbortController();
      ocrRunsRef.current.set(localId, controller);
      try {
        setOcrRunState(localId, { phase: "loading" });
        const { blob } = await apiDownloadAttachment(accessToken, cur.attachmentId);
        const engine = await defaultOcrDeps.makeEngine();
        const pages = await ocrAttachmentToTranscript(blob, {
          engine,
          makeRenderer: defaultOcrDeps.makeRenderer,
          onProgress: ({ page, total }) => setOcrRunState(localId, { phase: "ocr", page, total }),
          signal: controller.signal,
        });
        setOcrRunState(localId, { phase: "submitting" });
        const out = await apiPostAttachmentTranscript(accessToken, cur.attachmentId, {
          engine: engine.id,
          pages,
        });
        ocrSubmittedRef.current.set(cur.attachmentId, Date.now());
        patchStaged(localId)((s) => ({ ...s, status: out.status, error: out.error ?? null }));
      } catch (err) {
        if (err instanceof OcrAbortError) return;
        throw err;
      } finally {
        ocrRunsRef.current.delete(localId);
        setOcrRunState(localId, null);
      }
    },
    [accessToken, patchStaged, setOcrRunState],
  );

  const cancelAttachmentOcr = useCallback((localId: string) => {
    ocrRunsRef.current.get(localId)?.abort();
  }, []);

  return {
    stagedAttachments,
    ocrProgress,
    uploadAttachment,
    retryAttachment,
    unstageAttachment,
    consumeStagedAttachments,
    restoreStagedAttachments,
    saveAttachment,
    ocrAttachment,
    cancelAttachmentOcr,
  };
}
