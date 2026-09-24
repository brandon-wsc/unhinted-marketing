import { cjk } from "@streamdown/cjk";
import {
  Check,
  ChevronDown,
  Copy,
  CornerDownRight,
  Ellipsis,
  GitFork,
  Pencil,
  Square,
  Trash2,
} from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { Streamdown } from "streamdown";
import { IconButton } from "@/components/icon-button";
import { SendIcon } from "@/components/icons/send-icon";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/context/auth-context";
import { useToast } from "@/context/toast-context";
import { AnglePickCard } from "@/features/session/components/angle-pick-card";
import { InterruptCard } from "@/features/session/components/interrupt-card";
import { PreviewPanel } from "@/features/session/components/preview-panel";
import { RecommendedQuestions } from "@/features/session/components/recommended-questions";
import { SessionHistorySidebar } from "@/features/session/components/session-history";
import { SessionShell } from "@/features/session/components/session-shell";
import {
  agentNodeFallbackKey,
  agentNodeLabelKey,
  agentTrailHeader,
  isConfirmSuccessStatus,
  lastAgentActionNode,
  MAX_QUEUED_SESSION_MESSAGES,
  parseTurnDurationMs,
  QUEUE_TUCK_PX,
  shouldInterruptQueuedTurn,
  shouldRetryResumeImage,
} from "@/features/session/session-helpers";
import {
  getSessionChatRatio,
  type PagedPane,
  sessionLayoutMode,
  setSessionChatRatio,
} from "@/features/session/session-layout";
import type {
  AgentActionRecord,
  ChatMessage,
  DraftCopy,
  ForkRef,
  RecommendedQuestion,
  SessionBrief,
} from "@/features/session/types";
import { useRecommendedQuestions } from "@/features/session/use-recommended-questions";
import { useSession } from "@/features/session/use-session";
import { useContainerWidth } from "@/hooks/use-container-width";
import { useNow } from "@/hooks/use-now";
import { classifyRelativeTime, formatAbsoluteDateTime } from "@/lib/format-relative-time";
import { formatWorkedDuration, workedDurationLocale } from "@/lib/format-worked-duration";
import { mapApiError } from "@/lib/map-api-error";
import { cn } from "@/lib/utils";

const HISTORY_COLLAPSED_KEY = "unhinted.sessionHistory.collapsed";

/** Border-box plus overflowing descendants (tucked queue). */
function overlayStackHeight(el: HTMLElement): number {
  const wrap = el.getBoundingClientRect();
  let top = wrap.top;
  for (const node of el.querySelectorAll("*")) {
    const r = node.getBoundingClientRect();
    if (r.height > 0) top = Math.min(top, r.top);
  }
  return Math.max(0, Math.round(wrap.bottom - top));
}

export function ChatPanel() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { showError, showInfo } = useToast();
  const companyId = user?.organizations[0]?.id;
  const canPromoteExemplar =
    user?.organizations[0]?.role === "owner" || user?.organizations[0]?.role === "admin";
  const {
    session,
    messages,
    mode,
    sending,
    imageGenerating,
    stopping,
    queueFull,
    queuedMessages,
    streamingText,
    agentActions,
    brief,
    briefAfterMessageId,
    interruptAfterMessageId,
    previewAfterMessageId,
    awaitingImageOk,
    awaitingAnglePick,
    angleOptions,
    anglePersonas,
    recommendedPersona,
    recommendedImageFormat,
    canRetryAnglePick,
    draft,
    confirmReceipt,
    draftSaving,
    confirming,
    llmError,
    history,
    historyLoading,
    restoring,
    forkedFrom,
    forking,
    forkSession,
    sendMessage,
    enqueueQueuedMessage,
    dequeueQueuedMessage,
    resumeImage,
    chooseAngle,
    retryAnglePick,
    stopTurn,
    updateDraft,
    saveImagePlan,
    regenImage,
    addImage,
    removeImage,
    uploadImage,
    confirmPost,
    openSession,
    startNewChat,
    renameSession,
    pinSession,
    deleteSession,
    searchHistory,
    composerInput,
    setComposerInput,
    editInsertAt,
    setEditInsertAt,
  } = useSession(companyId);
  const {
    questions,
    loading: questionsLoading,
    generating: questionsGenerating,
    failed: questionsFailed,
    refresh: refreshQuestions,
  } = useRecommendedQuestions(companyId);
  const now = useNow();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [historyCollapsed, setHistoryCollapsed] = useState(() => {
    try {
      return localStorage.getItem(HISTORY_COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [pagedPane, setPagedPane] = useState<PagedPane>("chat");
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const composerObsRef = useRef<{
    resize: ResizeObserver;
    mutations: MutationObserver;
  } | null>(null);
  const [composerH, setComposerH] = useState(0);
  const composerRef = useCallback((el: HTMLDivElement | null) => {
    composerObsRef.current?.resize.disconnect();
    composerObsRef.current?.mutations.disconnect();
    composerObsRef.current = null;
    if (!el) return;
    // Hidden paged panes are display:none (0×0). Don't clobber a real height.
    const measure = () => {
      if (el.getClientRects().length === 0) return;
      setComposerH(overlayStackHeight(el));
    };
    const resize = new ResizeObserver(measure);
    const observeTree = () => {
      resize.observe(el);
      for (const node of el.querySelectorAll("*")) {
        resize.observe(node);
      }
    };
    observeTree();
    measure();
    const mutations = new MutationObserver(() => {
      observeTree();
      measure();
    });
    mutations.observe(el, { childList: true, subtree: true });
    composerObsRef.current = { resize, mutations };
  }, []);
  const { ref: shellRef, width: shellWidth } = useContainerWidth();
  const previewMode = mode === "PREVIEW" && !!draft;
  const layoutMode = sessionLayoutMode(shellWidth, {
    historyCollapsed,
    previewReady: previewMode,
  });
  const isSplit = layoutMode === "split";
  const composerCol = `mx-auto w-full px-4 sm:px-6 ${previewMode ? "max-w-none" : "max-w-3xl"}`;

  // Preview page only exists while a draft is ready — fall back to chat.
  useEffect(() => {
    if (!previewMode && pagedPane === "preview") {
      setPagedPane("chat");
    }
  }, [previewMode, pagedPane]);

  useEffect(() => {
    setConfirmError(null);
  }, [session?.id]);

  function goToChat() {
    setPagedPane("chat");
  }

  function toggleHistoryCollapsed() {
    setHistoryCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(HISTORY_COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }

  function handleSelectSession(id: string) {
    void openSession(id).catch(() => showError(t("chat.history.openFailed")));
    goToChat();
  }

  function handleNewChat() {
    void startNewChat()
      .then(() => goToChat())
      .catch(() => showError(t("chat.history.createFailed")));
  }

  async function handleRenameSession(id: string, title: string) {
    try {
      await renameSession(id, title);
    } catch {
      showError(t("chat.history.renameFailed"));
    }
  }

  async function handlePinSession(id: string, pinned: boolean) {
    try {
      await pinSession(id, pinned);
    } catch {
      showError(t("chat.history.pinFailed"));
    }
  }

  async function handleDeleteSession(id: string) {
    try {
      await deleteSession(id);
    } catch {
      showError(t("chat.history.deleteFailed"));
    }
  }

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [
    messages,
    sending,
    streamingText,
    agentActions,
    brief,
    awaitingImageOk,
    awaitingAnglePick,
    queuedMessages,
    composerH,
  ]);

  async function onSubmit(e?: FormEvent) {
    e?.preventDefault();
    if (stopping) return;
    const text = composerInput.trim();
    if (!text) return;
    const queueIndex = editInsertAt;
    if (sending && queueFull && queueIndex == null) return;
    setComposerInput("");
    setEditInsertAt(null);
    try {
      await sendMessage(text, queueIndex != null ? { queueIndex } : undefined);
    } catch {
      setComposerInput(text);
      setEditInsertAt(queueIndex);
      showError(t("chat.error.sendFailed"));
    }
  }

  function beginEditQueued(id: string) {
    const item = queuedMessages.find((q) => q.id === id);
    if (!item) return;
    if (editInsertAt != null) {
      const pending = composerInput.trim();
      if (pending && !enqueueQueuedMessage(pending, editInsertAt)) return;
    } else if (composerInput.trim()) {
      if (queuedMessages.length >= MAX_QUEUED_SESSION_MESSAGES) return;
      enqueueQueuedMessage(composerInput);
    }
    const removedAt = dequeueQueuedMessage(id);
    if (removedAt < 0) return;
    setComposerInput(item.content);
    setEditInsertAt(removedAt);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  function cancelQueuedEdit() {
    if (editInsertAt == null) return;
    const text = composerInput.trim();
    if (text) enqueueQueuedMessage(text, editInsertAt);
    setComposerInput("");
    setEditInsertAt(null);
  }

  async function onRetryLlmError(content?: string | null) {
    if (stopping) return;
    if (sending && queueFull) return;
    try {
      // At the angle gate a typed send is a NEW pick/feedback, not a resume —
      // Retry re-issues the failed pick; the card is the fallback affordance.
      if (awaitingAnglePick) {
        if (canRetryAnglePick) await retryAnglePick();
        return;
      }
      if (
        shouldRetryResumeImage({
          awaitingImageOk,
          lastAgentNode: lastAgentActionNode(agentActions),
        })
      ) {
        await resumeImage();
        return;
      }
      if (!content?.trim()) return;
      await sendMessage(content);
    } catch {
      showError(t("chat.error.sendFailed"));
    }
  }

  async function onForkMessage(messageId: string) {
    try {
      const note = await forkSession(messageId);
      goToChat();
      if (note === "carried_stale") showInfo(t("chat.fork.noteStale"));
      else if (note === "not_carried_later") showInfo(t("chat.fork.noteLater"));
    } catch {
      showError(t("chat.fork.failed"));
    }
  }

  async function onPickQuestion(question: RecommendedQuestion) {
    if (stopping) return;
    if (sending && queueFull) return;
    try {
      await sendMessage(question.text, { sourceQuestionId: question.id });
    } catch {
      showError(t("chat.error.sendFailed"));
    }
  }

  async function onResumeImageGen() {
    try {
      await resumeImage();
    } catch {
      showError(t("chat.error.sendFailed"));
    }
  }

  async function onPickAngle(
    angle: number | string,
    persona?: string,
    imageFormat?: "single" | "comic_4panel",
  ) {
    try {
      await chooseAngle(angle, persona, imageFormat);
    } catch {
      showError(t("chat.error.sendFailed"));
    }
  }

  async function onStopTurn() {
    try {
      await stopTurn();
    } catch {
      showError(t("chat.error.stopFailed"));
    }
  }

  async function onInterruptTurn() {
    try {
      await stopTurn("interrupt");
    } catch {
      showError(t("chat.error.stopFailed"));
    }
  }

  async function onApplyDraft(copy: DraftCopy) {
    try {
      await updateDraft(copy);
    } catch {
      showError(t("preview.error.saveFailed"));
    }
  }

  async function onConfirmDraft(copy: DraftCopy) {
    setConfirmError(null);
    try {
      await confirmPost(copy);
    } catch (err) {
      const detail = err instanceof Error ? err.message : "";
      setConfirmError(detail);
      showError(mapApiError(detail, t));
    }
  }

  async function onSavePlan(imageId: string, plan: Record<string, unknown>) {
    try {
      return await saveImagePlan(imageId, plan);
    } catch {
      showError(t("preview.error.planFailed"));
      return null;
    }
  }

  async function onRegenImage(imageId: string) {
    try {
      await regenImage(imageId);
    } catch {
      showError(t("preview.error.regenFailed"));
    }
  }

  async function onAddImage(format?: "single" | "comic_4panel") {
    try {
      return await addImage(format);
    } catch {
      showError(t("preview.error.addFailed"));
      return null;
    }
  }

  async function onRemoveImage(imageId: string) {
    try {
      return await removeImage(imageId);
    } catch {
      showError(t("preview.error.removeFailed"));
      return null;
    }
  }

  async function onUploadImage(imageId: string, file: File) {
    try {
      return await uploadImage(imageId, file);
    } catch {
      showError(t("preview.error.uploadFailed"));
      return null;
    }
  }

  const interruptOnEmptyEnter = shouldInterruptQueuedTurn({
    sending,
    stopping,
    queuedCount: queuedMessages.length,
    composerText: composerInput,
    editingQueued: editInsertAt != null,
    awaitingImageOk,
    awaitingAnglePick,
  });

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // isComposing guard: Enter must not send while a CJK IME candidate is open.
    if (stopping) return;
    if (e.key === "Escape" && editInsertAt != null) {
      e.preventDefault();
      cancelQueuedEdit();
      return;
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (interruptOnEmptyEnter) {
        void onInterruptTurn();
        return;
      }
      void onSubmit();
    }
  }

  const showLanding = messages.length === 0 && !sending && !stopping && streamingText === null;
  const confirmed =
    session?.status === "confirmed" || isConfirmSuccessStatus(confirmReceipt?.status);

  const historyProps = {
    sessions: history,
    loading: historyLoading,
    activeSessionId: session?.id ?? null,
    onSelect: handleSelectSession,
    onNewChat: handleNewChat,
    onRename: handleRenameSession,
    onPin: handlePinSession,
    onDelete: handleDeleteSession,
    onSearch: searchHistory,
  };

  const historySidebar = (
    <SessionHistorySidebar
      collapsed={historyCollapsed}
      onToggle={toggleHistoryCollapsed}
      {...historyProps}
    />
  );

  const anglePickCard = (
    <AnglePickCard
      angles={angleOptions}
      personas={anglePersonas}
      recommendedPersona={recommendedPersona}
      recommendedImageFormat={recommendedImageFormat}
      sending={sending || stopping}
      onPick={(angle, persona, imageFormat) => void onPickAngle(angle, persona, imageFormat)}
    />
  );

  const interruptCard = (
    <InterruptCard
      sending={sending || stopping}
      onResume={() => void onResumeImageGen()}
      onDiscard={() => void onStopTurn()}
    />
  );

  const chatColumn = (
    <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      {!isSplit && (
        <div className="absolute left-4 top-3 z-20">
          <button
            type="button"
            onClick={() => setPagedPane("record")}
            className="pointer-events-auto flex h-9 w-9 items-center justify-center rounded-full border border-border bg-card/90 text-muted-foreground backdrop-blur transition hover:border-voice-border hover:bg-accent hover:text-accent-foreground"
            title={t("chat.history.open")}
            aria-label={t("chat.history.open")}
          >
            <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden>
              <rect
                x="2"
                y="2.5"
                width="12"
                height="11"
                rx="1.5"
                stroke="currentColor"
                strokeWidth="1.2"
              />
              <path d="M6 2.5v11" stroke="currentColor" strokeWidth="1.2" />
            </svg>
          </button>
        </div>
      )}

      <div className="relative grid min-h-0 flex-1 grid-cols-1 grid-rows-1">
        <div
          ref={scrollRef}
          className="col-start-1 row-start-1 mb-8 min-h-0 overflow-y-auto [scrollbar-gutter:stable]"
        >
          <div
            className={`flex min-h-full w-full flex-col gap-5 ${composerCol} ${
              isSplit ? "pt-6" : "pt-14"
            }`}
            style={{ paddingBottom: composerH }}
          >
            {restoring ? (
              <p className="py-16 text-center text-sm text-muted-foreground">
                {t("chat.history.restoring")}
              </p>
            ) : showLanding ? (
              <div className="flex flex-1 flex-col items-center justify-center py-16 text-center sm:py-24">
                <h1 className="text-2xl font-semibold tracking-tight">
                  <span className="mr-1.5 text-voice" aria-hidden="true">
                    ✳
                  </span>
                  {t("chat.empty.title")}
                </h1>
                <p className="mt-2 max-w-md text-sm text-muted-foreground">
                  {t("chat.empty.subtitle")}
                </p>
                <RecommendedQuestions
                  questions={questions}
                  loading={questionsLoading}
                  generating={questionsGenerating}
                  failed={questionsFailed}
                  disabled={stopping || (sending && queueFull)}
                  onSelect={(q) => void onPickQuestion(q)}
                  onRetry={() => void refreshQuestions()}
                />
              </div>
            ) : (
              messages.map((m, index) => {
                const prevUser = findPreviousUserContent(messages, index);
                const turnActions = agentActions.filter((a) => a.afterMessageId === m.id);
                return (
                  <div key={m.id} className="flex flex-col gap-5">
                    <ChatMessageItem
                      message={m}
                      now={now}
                      retryDisabled={stopping || (sending && queueFull)}
                      onRetry={
                        awaitingImageOk || canRetryAnglePick || (!awaitingAnglePick && !!prevUser)
                          ? () => void onRetryLlmError(prevUser)
                          : undefined
                      }
                      onFork={() => void onForkMessage(m.id)}
                      forkDisabled={forking || stopping || sending}
                      onOpenFork={(id) => handleSelectSession(id)}
                    />
                    {m.metadata?.fork_point === true && forkedFrom && (
                      <ForkDivider
                        title={forkedFrom.title}
                        onOpen={
                          forkedFrom.session_id
                            ? () => handleSelectSession(forkedFrom.session_id!)
                            : undefined
                        }
                      />
                    )}
                    {turnActions.length > 0 && (
                      <AgentActionList
                        actions={turnActions}
                        persistedDurationMs={parseTurnDurationMs(m.metadata)}
                      />
                    )}
                    {brief && briefAfterMessageId === m.id && <BriefCard brief={brief} />}
                    {awaitingAnglePick && interruptAfterMessageId === m.id && anglePickCard}
                    {awaitingImageOk && interruptAfterMessageId === m.id && interruptCard}
                    {previewMode && previewAfterMessageId === m.id && !isSplit && (
                      <PreviewReadyBanner onOpen={() => setPagedPane("preview")} />
                    )}
                  </div>
                );
              })
            )}
            {/* Fallback if anchor message was replaced / missing — keep cards visible. */}
            {agentActions.some(
              (a) => !a.afterMessageId || !messages.some((m) => m.id === a.afterMessageId),
            ) && (
              <AgentActionList
                key={session?.id ?? "none"}
                actions={agentActions.filter(
                  (a) => !a.afterMessageId || !messages.some((m) => m.id === a.afterMessageId),
                )}
                persistedDurationMs={null}
              />
            )}
            {brief &&
              briefAfterMessageId &&
              !messages.some((m) => m.id === briefAfterMessageId) && <BriefCard brief={brief} />}
            {awaitingAnglePick &&
              interruptAfterMessageId &&
              !messages.some((m) => m.id === interruptAfterMessageId) &&
              anglePickCard}
            {awaitingImageOk &&
              interruptAfterMessageId &&
              !messages.some((m) => m.id === interruptAfterMessageId) &&
              interruptCard}
            {previewMode &&
              previewAfterMessageId &&
              !messages.some((m) => m.id === previewAfterMessageId) &&
              !isSplit && <PreviewReadyBanner onOpen={() => setPagedPane("preview")} />}
            {brief && !briefAfterMessageId && <BriefCard brief={brief} />}
            {awaitingAnglePick && !interruptAfterMessageId && anglePickCard}
            {awaitingImageOk && !interruptAfterMessageId && interruptCard}
            {previewMode && !previewAfterMessageId && !isSplit && (
              <PreviewReadyBanner onOpen={() => setPagedPane("preview")} />
            )}
            {/* Inline LLM error when failed before an assistant row was persisted. */}
            {llmError && !messages.some((m) => isLlmErrorContent(m.content)) && (
              <LlmErrorCard
                message={llmError}
                retryDisabled={stopping || (sending && queueFull)}
                onRetry={
                  awaitingImageOk ||
                  canRetryAnglePick ||
                  (!awaitingAnglePick && !!findLastUserContent(messages))
                    ? () => void onRetryLlmError(findLastUserContent(messages))
                    : undefined
                }
              />
            )}
            {streamingText !== null && (
              <div className="text-sm leading-relaxed">
                <Streamdown mode="streaming" plugins={{ cjk }}>
                  {streamingText}
                </Streamdown>
              </div>
            )}
          </div>
        </div>

        <div className="pointer-events-none col-start-1 row-start-1 z-10 flex flex-col justify-end overflow-y-auto pb-4 [scrollbar-gutter:stable]">
          <div ref={composerRef}>
            <form
              onSubmit={onSubmit}
              className={`pointer-events-auto flex flex-col gap-1.5 ${composerCol}`}
            >
              {interruptOnEmptyEnter ||
              ((awaitingImageOk || awaitingAnglePick) && queuedMessages.length > 0) ||
              queueFull ? (
                <div className="space-y-0.5 px-1 text-[11px] leading-snug text-muted-foreground">
                  {interruptOnEmptyEnter ? <p>{t("chat.queue.interrupt")}</p> : null}
                  {awaitingImageOk && queuedMessages.length > 0 ? (
                    <p>{t("chat.queue.holdForImage")}</p>
                  ) : null}
                  {awaitingAnglePick && queuedMessages.length > 0 ? (
                    <p>{t("chat.queue.holdForAngle")}</p>
                  ) : null}
                  {queueFull ? <p>{t("chat.queue.full")}</p> : null}
                </div>
              ) : null}
              <div className="relative">
                {queuedMessages.length > 0 ? (
                  <div
                    className="absolute inset-x-3 z-0 overflow-hidden rounded-2xl border border-voice-border bg-card"
                    style={{
                      bottom: `calc(100% - ${QUEUE_TUCK_PX}px)`,
                      paddingBottom: QUEUE_TUCK_PX,
                    }}
                  >
                    <ul className="flex flex-col p-1">
                      {queuedMessages.map((item) => (
                        <li
                          key={item.id}
                          className="group flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12px] leading-tight text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                        >
                          <CornerDownRight className="size-3 shrink-0 text-voice" aria-hidden />
                          <span className="min-w-0 flex-1 truncate">{item.content}</span>
                          <div className="flex shrink-0 items-center gap-0.5 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 has-[[data-state=open]]:opacity-100">
                            <IconButton
                              type="button"
                              className="h-6 w-6"
                              title={t("chat.queue.remove")}
                              aria-label={t("chat.queue.remove")}
                              onClick={() => dequeueQueuedMessage(item.id)}
                            >
                              <Trash2 className="size-3" />
                            </IconButton>
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <IconButton
                                  type="button"
                                  className="h-6 w-6"
                                  title={t("chat.queue.more")}
                                  aria-label={t("chat.queue.more")}
                                >
                                  <Ellipsis className="size-3" />
                                </IconButton>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end" className="w-40">
                                <DropdownMenuItem onSelect={() => beginEditQueued(item.id)}>
                                  <Pencil className="size-3.5" />
                                  {t("chat.queue.edit")}
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <div className="relative z-10 flex flex-col rounded-2xl border border-border bg-card px-3 py-2 shadow-sm transition-colors hover:border-voice-border focus-within:border-voice focus-within:hover:border-voice">
                  <Textarea
                    ref={inputRef}
                    value={composerInput}
                    onChange={(e) => setComposerInput(e.target.value)}
                    onKeyDown={onKeyDown}
                    rows={2}
                    placeholder={t("chat.input.placeholder")}
                    disabled={stopping}
                    className="block max-h-40 min-h-16 w-full resize-none overflow-y-auto border-0 bg-transparent px-2 py-1.5 shadow-none not-read-only:hover:border-0 not-read-only:focus-visible:border-0 not-read-only:focus-visible:ring-0 not-read-only:focus-visible:hover:border-0"
                  />
                  <div className="flex items-center justify-end gap-1 px-1">
                    {(sending || stopping) && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        disabled={stopping}
                        onClick={() => void onStopTurn()}
                        className="h-8 w-8 rounded-full text-foreground"
                        title={stopping ? t("chat.stopping") : t("chat.stop")}
                        aria-label={stopping ? t("chat.stopping") : t("chat.stop")}
                      >
                        <Square className="size-3.5" fill="currentColor" stroke="none" />
                      </Button>
                    )}
                    <Button
                      type="submit"
                      variant="ghost"
                      size="icon"
                      disabled={
                        stopping ||
                        !composerInput.trim() ||
                        (sending && queueFull && editInsertAt == null)
                      }
                      className="h-8 w-8 rounded-full text-foreground"
                      title={t("chat.send")}
                      aria-label={t("chat.send")}
                    >
                      <SendIcon className="size-[18px]" />
                    </Button>
                  </div>
                </div>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );

  const previewPane =
    draft && previewMode ? (
      <PreviewPanel
        draft={draft}
        confirmed={confirmed}
        confirmReceipt={confirmReceipt}
        draftSaving={draftSaving}
        confirming={confirming}
        confirmError={confirmError}
        companyId={companyId}
        canPromoteExemplar={canPromoteExemplar}
        onApply={onApplyDraft}
        onConfirm={onConfirmDraft}
        onSavePlan={onSavePlan}
        onRegenImage={onRegenImage}
        onAddImage={onAddImage}
        onRemoveImage={onRemoveImage}
        onUploadImage={onUploadImage}
        paged={!isSplit}
        onBack={goToChat}
        awaitingImage={awaitingImageOk}
        imageGenerating={imageGenerating}
      />
    ) : null;

  return (
    <SessionShell
      shellRef={shellRef}
      layoutMode={layoutMode}
      pagedPane={pagedPane}
      previewReady={previewMode}
      historyCollapsed={historyCollapsed}
      shellWidth={shellWidth}
      chatRatio={getSessionChatRatio()}
      onChatRatioChange={setSessionChatRatio}
      history={historySidebar}
      historyPage={
        <SessionHistorySidebar
          collapsed={false}
          onToggle={() => undefined}
          pageMode
          onBack={goToChat}
          {...historyProps}
        />
      }
      chat={chatColumn}
      preview={previewPane}
    />
  );
}

function PreviewReadyBanner({ onOpen }: { onOpen: () => void }) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onOpen}
      className="rounded-xl border border-border bg-card px-3 py-2 text-left text-xs text-muted-foreground transition hover:border-voice-border hover:bg-accent hover:text-accent-foreground"
    >
      {t("preview.readyBanner")}
    </button>
  );
}

function AgentActionList({
  actions,
  persistedDurationMs,
}: {
  actions: AgentActionRecord[];
  persistedDurationMs: number | null;
}) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(true);
  const startedAtRef = useRef<number | null>(null);
  const [frozenMs, setFrozenMs] = useState<number | null>(null);

  const running = actions.some((action) => action.status === "running");
  if (running && startedAtRef.current == null) {
    startedAtRef.current = Date.now();
  }

  useEffect(() => {
    if (running || startedAtRef.current == null) return;
    if (persistedDurationMs != null || frozenMs != null) return;
    setFrozenMs(Math.max(0, Date.now() - startedAtRef.current));
  }, [running, persistedDurationMs, frozenMs]);

  const elapsedMs = persistedDurationMs ?? frozenMs;
  const header = agentTrailHeader(running, elapsedMs);
  const locale = workedDurationLocale(i18n.language);
  const headerLabel =
    header?.kind === "working"
      ? t("chat.agent.working")
      : header?.kind === "workedFor"
        ? t("chat.agent.workedFor", {
            duration: formatWorkedDuration(header.durationMs, locale),
          })
        : null;
  const expanded = headerLabel ? open : true;

  if (actions.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5 py-0.5">
      {headerLabel ? (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setOpen((value) => !value)}
          className="flex items-center gap-1 self-start text-xs leading-snug text-muted-foreground hover:text-foreground"
        >
          <span>{headerLabel}</span>
          <ChevronDown
            className={cn("size-3.5 shrink-0 transition-transform", expanded ? "" : "-rotate-90")}
            aria-hidden
          />
        </button>
      ) : null}
      {expanded ? (
        <ul className="flex flex-col gap-1.5" aria-label={t("chat.agent.actions")}>
          {actions.map((action) => {
            const label = t(agentNodeLabelKey(action.node, action.status), {
              defaultValue: t(agentNodeFallbackKey(action.status)),
            });
            const isRunning = action.status === "running";
            return (
              <li
                key={action.id}
                className={cn(
                  "flex items-start gap-2 text-xs leading-snug",
                  isRunning ? "text-voice" : "text-muted-foreground",
                )}
              >
                <span
                  className={cn(
                    "mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center",
                    isRunning ? "text-voice" : "text-muted-foreground",
                  )}
                >
                  {isRunning ? (
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-voice" />
                  ) : (
                    <Check className="size-3.5" aria-hidden />
                  )}
                </span>
                <span className="min-w-0">{label}</span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

function BriefCard({ brief }: { brief: SessionBrief }) {
  const { t } = useTranslation();
  const sections: { title: string; items: string[] }[] = [
    { title: t("chat.agent.brief.canDo"), items: brief.can_do },
    { title: t("chat.agent.brief.cannotDo"), items: brief.cannot_do },
    { title: t("chat.agent.brief.angles"), items: brief.angles },
  ].filter((s) => s.items.length > 0);

  return (
    <div className="rounded-xl border border-border bg-card p-4 text-sm shadow-sm">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("chat.agent.brief.title")}
        </span>
        {brief.persona && (
          <span className="rounded-md border border-border px-1.5 py-0.5 text-[11px] leading-none text-muted-foreground">
            {brief.persona}
          </span>
        )}
      </div>
      {brief.summary && <p className="mb-3 leading-relaxed">{brief.summary}</p>}
      <div className="flex flex-col gap-3">
        {sections.map((section) => (
          <div key={section.title}>
            <p className="mb-1 text-xs font-medium text-muted-foreground">{section.title}</p>
            <ul className="list-disc space-y-0.5 pl-5 leading-relaxed">
              {section.items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function isLlmErrorContent(content: string): boolean {
  return content.startsWith("AI 服務暫時唔可用") || content.startsWith("AI service unavailable");
}

function findPreviousUserContent(messages: ChatMessage[], index: number): string | null {
  for (let i = index - 1; i >= 0; i -= 1) {
    if (messages[i]?.role === "user") return messages[i]!.content;
  }
  return null;
}

function findLastUserContent(messages: ChatMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i]?.role === "user") return messages[i]!.content;
  }
  return null;
}

function LlmErrorCard({
  message,
  onRetry,
  retryDisabled,
}: {
  message: string;
  onRetry?: () => void;
  retryDisabled?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="flex flex-col gap-3 rounded-xl border border-destructive/40 bg-destructive-soft px-4 py-3 text-sm text-destructive-foreground shadow-sm sm:flex-row sm:items-start sm:justify-between"
      role="alert"
    >
      <p className="min-w-0 flex-1 whitespace-pre-wrap leading-relaxed">{message}</p>
      {onRetry && (
        <Button
          type="button"
          variant="ghost"
          disabled={retryDisabled}
          onClick={onRetry}
          className="shrink-0 border border-destructive/40 text-destructive-foreground hover:bg-destructive/10"
        >
          {t("chat.error.retry")}
        </Button>
      )}
    </div>
  );
}

function ChatMessageItem({
  message,
  now,
  onRetry,
  retryDisabled,
  onFork,
  forkDisabled,
  onOpenFork,
}: {
  message: ChatMessage;
  now: Date;
  onRetry?: () => void;
  retryDisabled?: boolean;
  onFork?: () => void;
  forkDisabled?: boolean;
  onOpenFork?: (sessionId: string) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="flex max-w-[85%] flex-col sm:max-w-[75%]">
          <div className="whitespace-pre-wrap rounded-2xl bg-primary px-4 py-2.5 text-sm text-primary-foreground">
            {message.content}
          </div>
          <MessageMeta
            align="user"
            content={message.content}
            createdAt={message.created_at}
            now={now}
          />
        </div>
      </div>
    );
  }
  if (isLlmErrorContent(message.content)) {
    return (
      <LlmErrorCard message={message.content} onRetry={onRetry} retryDisabled={retryDisabled} />
    );
  }
  return (
    <div className="text-sm leading-relaxed">
      <Streamdown mode="static" plugins={{ cjk }}>
        {message.content}
      </Streamdown>
      <MessageMeta
        align="assistant"
        content={message.content}
        createdAt={message.created_at}
        now={now}
        onFork={onFork}
        forkDisabled={forkDisabled}
      />
      {message.forks && message.forks.length > 0 && onOpenFork && (
        <ForksChip forks={message.forks} onOpen={onOpenFork} />
      )}
    </div>
  );
}

function ForkDividerRow({ children }: { children: ReactNode }) {
  return (
    <div className="flex w-full min-w-0 items-center gap-2 text-[11px] text-muted-foreground">
      <div className="h-px min-w-4 flex-1 bg-border" aria-hidden />
      {children}
      <div className="h-px min-w-4 flex-1 bg-border" aria-hidden />
    </div>
  );
}

function ForkDivider({ title, onOpen }: { title?: string | null; onOpen?: () => void }) {
  const { t } = useTranslation();
  const label = t("chat.fork.divider", { title: title || t("chat.history.untitled") });
  return (
    <ForkDividerRow>
      {onOpen ? (
        <button
          type="button"
          onClick={onOpen}
          title={label}
          className="flex min-w-0 items-center gap-1.5 rounded-md px-1 py-0.5 transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          <GitFork className="size-3 shrink-0" aria-hidden />
          <span className="min-w-0 truncate">{label}</span>
        </button>
      ) : (
        <>
          <GitFork className="size-3 shrink-0" aria-hidden />
          <span className="min-w-0 truncate" title={label}>
            {label}
          </span>
        </>
      )}
    </ForkDividerRow>
  );
}

function ForksChip({ forks, onOpen }: { forks: ForkRef[]; onOpen: (sessionId: string) => void }) {
  const { t } = useTranslation();
  const untitled = t("chat.history.untitled");
  const label =
    forks.length === 1
      ? t("chat.fork.toOne", { title: forks[0]!.title || untitled })
      : t("chat.fork.toMany", { n: forks.length });
  return (
    <div className="mt-1">
      <ForkDividerRow>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              title={label}
              className="flex min-w-0 items-center gap-1.5 rounded-md px-1 py-0.5 transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              <GitFork className="size-3 shrink-0" aria-hidden />
              <span className="min-w-0 truncate">{label}</span>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="center" className="w-56">
            {forks.map((f) => (
              <DropdownMenuItem key={f.session_id} onSelect={() => onOpen(f.session_id)}>
                <GitFork className="size-3.5 shrink-0" aria-hidden />
                <span className="truncate">{f.title || untitled}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </ForkDividerRow>
    </div>
  );
}

function MessageMeta({
  align,
  content,
  createdAt,
  now,
  onFork,
  forkDisabled,
}: {
  align: "user" | "assistant";
  content: string;
  createdAt: string;
  now: Date;
  onFork?: () => void;
  forkDisabled?: boolean;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(id);
  }, [copied]);

  const relative = classifyRelativeTime(createdAt, now);
  const absolute = formatAbsoluteDateTime(createdAt);
  const timeLabel =
    relative.kind === "relative"
      ? t(`chat.message.time.${relative.unit}`, { n: relative.n })
      : relative.kind === "absolute"
        ? relative.text
        : null;

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const copyButton = (
    <Tooltip>
      <TooltipTrigger asChild>
        <IconButton
          type="button"
          className="h-6 w-6"
          aria-label={copied ? t("chat.message.copied") : t("chat.message.copy")}
          onClick={() => void onCopy()}
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        </IconButton>
      </TooltipTrigger>
      <TooltipContent side="top">
        {copied ? t("chat.message.copied") : t("chat.message.copy")}
      </TooltipContent>
    </Tooltip>
  );

  const forkButton = onFork ? (
    <Tooltip>
      <TooltipTrigger asChild>
        <IconButton
          type="button"
          className="h-6 w-6"
          aria-label={t("chat.message.fork")}
          disabled={forkDisabled}
          onClick={onFork}
        >
          <GitFork className="size-3.5" />
        </IconButton>
      </TooltipTrigger>
      <TooltipContent side="top">{t("chat.message.fork")}</TooltipContent>
    </Tooltip>
  ) : null;

  const timeLabelNode =
    timeLabel && absolute ? (
      <Tooltip>
        <TooltipTrigger asChild>
          <time
            dateTime={createdAt}
            className="cursor-default text-[11px] tabular-nums text-muted-foreground"
          >
            {timeLabel}
          </time>
        </TooltipTrigger>
        <TooltipContent side="top">{absolute}</TooltipContent>
      </Tooltip>
    ) : null;

  return (
    <div
      className={cn(
        "mt-1 flex items-center gap-1 sm:gap-1.5",
        align === "user" ? "justify-end" : "justify-start",
      )}
    >
      {align === "user" ? (
        <>
          {timeLabelNode}
          {copyButton}
        </>
      ) : (
        <>
          {copyButton}
          {forkButton}
          {timeLabelNode}
        </>
      )}
    </div>
  );
}
