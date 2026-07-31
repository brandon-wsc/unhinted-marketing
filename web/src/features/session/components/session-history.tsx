import {
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import type { SessionListItem } from "@/features/session/types";

type Props = {
  collapsed: boolean;
  onToggle: () => void;
  sessions: SessionListItem[];
  loading: boolean;
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onNewChat: () => void;
  onRename: (sessionId: string, title: string) => Promise<unknown>;
  onPin: (sessionId: string, pinned: boolean) => Promise<unknown>;
  onDelete: (sessionId: string) => Promise<unknown>;
  /** Full-bleed page (mobile) — stretch width; pair with onBack. */
  pageMode?: boolean;
  onBack?: () => void;
};

type HistoryGroup = {
  key: string;
  label: string;
  items: SessionListItem[];
};

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function groupUnpinned(
  sessions: SessionListItem[],
  labels: { today: string; yesterday: string; week: string; older: string },
): HistoryGroup[] {
  const now = new Date();
  const today = startOfDay(now);
  const yesterday = today - 86_400_000;
  const weekAgo = today - 7 * 86_400_000;

  const buckets: Record<string, SessionListItem[]> = {
    today: [],
    yesterday: [],
    week: [],
    older: [],
  };

  for (const s of sessions) {
    const t = startOfDay(new Date(s.updated_at));
    if (t >= today) buckets.today.push(s);
    else if (t >= yesterday) buckets.yesterday.push(s);
    else if (t >= weekAgo) buckets.week.push(s);
    else buckets.older.push(s);
  }

  return (
    [
      { key: "today", label: labels.today, items: buckets.today },
      { key: "yesterday", label: labels.yesterday, items: buckets.yesterday },
      { key: "week", label: labels.week, items: buckets.week },
      { key: "older", label: labels.older, items: buckets.older },
    ] as const
  ).filter((g) => g.items.length > 0);
}

export function SessionHistorySidebar({
  collapsed,
  onToggle,
  sessions,
  loading,
  activeSessionId,
  onSelect,
  onNewChat,
  onRename,
  onPin,
  onDelete,
  pageMode = false,
  onBack,
}: Props) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [menuId, setMenuId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((s) => {
      const title = (s.title || "").toLowerCase();
      return title.includes(q) || s.id.toLowerCase().includes(q);
    });
  }, [sessions, query]);

  const pinned = useMemo(() => filtered.filter((s) => !!s.pinned), [filtered]);
  const unpinned = useMemo(() => filtered.filter((s) => !s.pinned), [filtered]);

  const groups = useMemo(
    () =>
      groupUnpinned(unpinned, {
        today: t("chat.history.group.today"),
        yesterday: t("chat.history.group.yesterday"),
        week: t("chat.history.group.week"),
        older: t("chat.history.group.older"),
      }),
    [unpinned, t],
  );

  async function handleRename(id: string, title: string) {
    setBusyId(id);
    try {
      await onRename(id, title);
      setRenamingId(null);
    } finally {
      setBusyId(null);
    }
  }

  async function handlePin(id: string, pinnedNext: boolean) {
    setMenuId(null);
    setBusyId(id);
    try {
      await onPin(id, pinnedNext);
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(id: string) {
    setBusyId(id);
    try {
      await onDelete(id);
      setConfirmDeleteId(null);
      setMenuId(null);
    } finally {
      setBusyId(null);
    }
  }

  function renderRow(s: SessionListItem) {
    const active = s.id === activeSessionId;
    const title = s.title?.trim() || t("chat.history.untitled");
    const renaming = renamingId === s.id;
    const menuOpen = menuId === s.id;
    const busy = busyId === s.id;

    return (
      <li key={s.id} className="group relative">
        {renaming ? (
          <RenameField
            initial={s.title?.trim() || ""}
            disabled={busy}
            onCancel={() => setRenamingId(null)}
            onSubmit={(next) => void handleRename(s.id, next)}
          />
        ) : (
          <div
            className={`flex items-center gap-0.5 rounded-full transition ${
              active
                ? "bg-[var(--color-hover)]"
                : "hover:bg-[var(--color-hover)]"
            }`}
          >
            <button
              type="button"
              onClick={() => onSelect(s.id)}
              className="min-w-0 flex-1 truncate px-3 py-2 text-left text-[13px] leading-snug text-[var(--color-foreground)]"
              title={title}
            >
              {s.pinned ? (
                <span className="mr-1.5 inline-flex text-[var(--color-muted)]" aria-hidden>
                  <PinIcon filled />
                </span>
              ) : null}
              {title}
            </button>
            <div className="relative shrink-0 pr-1">
              <button
                type="button"
                className={`flex h-7 w-7 items-center justify-center rounded-full text-[var(--color-muted)] transition hover:bg-[var(--color-card)] hover:text-[var(--color-foreground)] ${
                  menuOpen ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus:opacity-100"
                }`}
                aria-label={t("chat.history.more")}
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                onClick={(e) => {
                  e.stopPropagation();
                  setMenuId((prev) => (prev === s.id ? null : s.id));
                }}
              >
                <MoreIcon />
              </button>
              {menuOpen && (
                <SessionRowMenu
                  pinned={!!s.pinned}
                  onClose={() => setMenuId(null)}
                  onPin={() => void handlePin(s.id, !s.pinned)}
                  onRename={() => {
                    setMenuId(null);
                    setRenamingId(s.id);
                  }}
                  onDelete={() => {
                    setMenuId(null);
                    setConfirmDeleteId(s.id);
                  }}
                />
              )}
            </div>
          </div>
        )}
      </li>
    );
  }

  if (collapsed) {
    return (
      <aside className="flex h-full min-h-0 w-12 shrink-0 flex-col items-center gap-2 overflow-hidden border-r border-[var(--color-border)] bg-[var(--color-background)] py-3">
        <button
          type="button"
          onClick={onToggle}
          className="flex h-8 w-8 items-center justify-center rounded-full text-[var(--color-muted)] transition hover:bg-[var(--color-hover)] hover:text-[var(--color-foreground)]"
          title={t("chat.history.open")}
          aria-label={t("chat.history.open")}
        >
          <SidebarIcon />
        </button>
        <button
          type="button"
          onClick={onNewChat}
          className="flex h-8 w-8 items-center justify-center rounded-full text-[var(--color-muted)] transition hover:bg-[var(--color-hover)] hover:text-[var(--color-foreground)]"
          title={t("chat.history.new")}
          aria-label={t("chat.history.new")}
        >
          <PlusIcon />
        </button>
      </aside>
    );
  }

  return (
    <aside
      className={`flex h-full min-h-0 shrink-0 flex-col overflow-hidden bg-[var(--color-background)] ${
        pageMode
          ? "w-full"
          : "w-[280px] border-r border-[var(--color-border)]"
      }`}
    >
      <div className="flex shrink-0 items-center gap-1 px-3 pb-1 pt-3">
        {pageMode && onBack ? (
          <button
            type="button"
            onClick={onBack}
            className="flex h-9 shrink-0 items-center gap-1 rounded-full px-2.5 text-sm text-[var(--color-muted)] transition hover:bg-[var(--color-hover)] hover:text-[var(--color-foreground)]"
            aria-label={t("chat.mobile.back")}
          >
            <BackIcon />
            {t("chat.mobile.back")}
          </button>
        ) : !pageMode ? (
          <button
            type="button"
            onClick={onToggle}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[var(--color-muted)] transition hover:bg-[var(--color-hover)] hover:text-[var(--color-foreground)]"
            title={t("chat.history.collapse")}
            aria-label={t("chat.history.collapse")}
          >
            <SidebarIcon />
          </button>
        ) : null}
        <button
          type="button"
          onClick={onNewChat}
          className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded-full bg-[var(--color-card)] px-3 text-sm font-medium text-[var(--color-foreground)] shadow-sm ring-1 ring-[var(--color-border)] transition hover:bg-[var(--color-hover)]"
        >
          <PlusIcon />
          {t("chat.history.new")}
        </button>
      </div>

      <div className="shrink-0 px-3 pb-2 pt-2">
        <div className="relative">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-muted)]">
            <SearchIcon />
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("chat.history.search")}
            className="w-full rounded-full border-0 bg-[var(--color-card)] py-2 pl-9 pr-3 text-sm outline-none ring-1 ring-[var(--color-border)] transition placeholder:text-[var(--color-muted)] focus:ring-[var(--color-ring)]"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {loading && sessions.length === 0 ? (
          <p className="px-3 py-8 text-center text-xs text-[var(--color-muted)]">
            {t("chat.history.loading")}
          </p>
        ) : pinned.length === 0 && groups.length === 0 ? (
          <p className="px-3 py-8 text-center text-xs text-[var(--color-muted)]">
            {t("chat.history.empty")}
          </p>
        ) : (
          <>
            {pinned.length > 0 && (
              <div className="mb-2">
                <p className="px-3 pb-1 pt-2 text-[11px] font-medium text-[var(--color-muted)]">
                  {t("chat.history.group.pinned")}
                </p>
                <ul className="flex flex-col gap-0.5">{pinned.map(renderRow)}</ul>
              </div>
            )}
            {groups.map((group) => (
              <div key={group.key} className="mb-2">
                <p className="px-3 pb-1 pt-2 text-[11px] font-medium text-[var(--color-muted)]">
                  {group.label}
                </p>
                <ul className="flex flex-col gap-0.5">{group.items.map(renderRow)}</ul>
              </div>
            ))}
          </>
        )}
      </div>

      {confirmDeleteId && (
        <DeleteConfirmDialog
          busy={busyId === confirmDeleteId}
          onCancel={() => setConfirmDeleteId(null)}
          onConfirm={() => void handleDelete(confirmDeleteId)}
        />
      )}
    </aside>
  );
}

function RenameField({
  initial,
  disabled,
  onCancel,
  onSubmit,
}: {
  initial: string;
  disabled?: boolean;
  onCancel: () => void;
  onSubmit: (title: string) => void;
}) {
  const { t } = useTranslation();
  const [value, setValue] = useState(initial);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  function submit(e?: FormEvent) {
    e?.preventDefault();
    onSubmit(value);
  }

  function onKeyDown(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    }
  }

  return (
    <form onSubmit={submit} className="px-1 py-0.5">
      <input
        ref={inputRef}
        value={value}
        disabled={disabled}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => submit()}
        maxLength={200}
        aria-label={t("chat.history.rename")}
        className="w-full rounded-full bg-[var(--color-card)] px-3 py-2 text-[13px] outline-none ring-2 ring-[var(--color-ring)]"
      />
    </form>
  );
}

function SessionRowMenu({
  pinned,
  onClose,
  onPin,
  onRename,
  onDelete,
}: {
  pinned: boolean;
  onClose: () => void;
  onPin: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) onClose();
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose]);

  return (
    <div
      ref={rootRef}
      role="menu"
      className="absolute right-0 top-full z-30 mt-1 w-40 overflow-hidden rounded-xl border border-[var(--color-border)] bg-[var(--color-card)] py-1 shadow-lg"
    >
      <MenuButton onClick={onPin}>
        <PinIcon filled={pinned} />
        {pinned ? t("chat.history.unpin") : t("chat.history.pin")}
      </MenuButton>
      <MenuButton onClick={onRename}>
        <RenameIcon />
        {t("chat.history.rename")}
      </MenuButton>
      <MenuButton onClick={onDelete} danger>
        <TrashIcon />
        {t("chat.history.delete")}
      </MenuButton>
    </div>
  );
}

function MenuButton({
  onClick,
  children,
  danger,
}: {
  onClick: () => void;
  children: ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition ${
        danger
          ? "text-[var(--color-destructive-text)] hover:bg-[var(--color-destructive-soft)]"
          : "text-[var(--color-foreground)] hover:bg-[var(--color-hover)]"
      }`}
    >
      {children}
    </button>
  );
}

function DeleteConfirmDialog({
  busy,
  onCancel,
  onConfirm,
}: {
  busy?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/45"
        aria-label={t("chat.history.close")}
        onClick={onCancel}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-chat-title"
        className="relative w-full max-w-sm rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] p-5 shadow-xl"
      >
        <h2 id="delete-chat-title" className="text-base font-semibold">
          {t("chat.history.deleteTitle")}
        </h2>
        <p className="mt-2 text-sm text-[var(--color-muted)]">
          {t("chat.history.deleteBody")}
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={onCancel}
            className="rounded-full px-4 py-2 text-sm font-medium text-[var(--color-foreground)] transition hover:bg-[var(--color-hover)]"
          >
            {t("chat.history.cancel")}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onConfirm}
            className="rounded-full px-4 py-2 text-sm font-medium text-white transition"
            style={{ backgroundColor: "var(--color-destructive)" }}
          >
            {busy ? t("chat.history.deleting") : t("chat.history.delete")}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Mobile: left sheet overlay. */
export function SessionHistoryMobileSheet({
  open,
  onClose,
  sessions,
  loading,
  activeSessionId,
  onSelect,
  onNewChat,
  onRename,
  onPin,
  onDelete,
}: {
  open: boolean;
  onClose: () => void;
  sessions: SessionListItem[];
  loading: boolean;
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
  onNewChat: () => void;
  onRename: (sessionId: string, title: string) => Promise<unknown>;
  onPin: (sessionId: string, pinned: boolean) => Promise<unknown>;
  onDelete: (sessionId: string) => Promise<unknown>;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex md:hidden">
      <button
        type="button"
        className="absolute inset-0 bg-black/40"
        aria-label="Close"
        onClick={onClose}
      />
      <div className="relative h-full w-[280px] max-w-[85vw] shadow-xl [&_aside]:border-r-0">
        <SessionHistorySidebar
          collapsed={false}
          onToggle={onClose}
          sessions={sessions}
          loading={loading}
          activeSessionId={activeSessionId}
          onSelect={(id) => {
            onSelect(id);
            onClose();
          }}
          onNewChat={() => {
            onNewChat();
            onClose();
          }}
          onRename={onRename}
          onPin={onPin}
          onDelete={onDelete}
        />
      </div>
    </div>
  );
}

function BackIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M10 3.5 5.5 8 10 12.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function SidebarIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="none" aria-hidden>
      <rect x="2" y="2.5" width="12" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
      <path d="M6 2.5v11" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.2" />
      <path d="M10.5 10.5 13.5 13.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

function MoreIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
      <circle cx="8" cy="3.5" r="1.2" />
      <circle cx="8" cy="8" r="1.2" />
      <circle cx="8" cy="12.5" r="1.2" />
    </svg>
  );
}

function PinIcon({ filled }: { filled?: boolean }) {
  if (filled) {
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden>
        <path d="M9.8 2.2a1 1 0 0 0-1.4 0L6.2 4.4 4.5 3.9a.75.75 0 0 0-.8 1.2l2.1 2.1-.9 3.3a.75.75 0 0 0 1.1.85l2.9-1.5 2.1 2.1a.75.75 0 1 0 1.06-1.06l-.5-1.7 2.2-2.2a1 1 0 0 0 0-1.4L9.8 2.2Z" />
      </svg>
    );
  }
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M9.6 2.6 13.4 6.4M6.3 4.6 4.6 4.1a.6.6 0 0 0-.64.96l2 2-.85 3.15a.6.6 0 0 0 .88.68l2.75-1.42 2 2a.6.6 0 0 0 .85-.85l-.48-1.6 2.05-2.05"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function RenameIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M9.5 3.5 12.5 6.5M3 13l.7-2.8L10.2 3.7a1.2 1.2 0 0 1 1.7 0l.4.4a1.2 1.2 0 0 1 0 1.7L5.8 12.3 3 13Z"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M3.5 4.5h9M6.5 4.5V3.2a.7.7 0 0 1 .7-.7h1.6a.7.7 0 0 1 .7.7v1.3M5 4.5l.5 8.2a.8.8 0 0 0 .8.7h3.4a.8.8 0 0 0 .8-.7L11 4.5"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
