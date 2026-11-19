---
name: web-ui-system
description: Unhinted web UI rules — shadcn ui/* layer ownership, semantic theme tokens, accent vs secondary washes, table/field states, SelectContent popper, content-based split/paged session layout, zh-HK copy split. Use when creating, editing, or reviewing anything under web/src/.
---

# Web UI system — Unhinted

| Layer | Role |
|-------|------|
| `web/src/components/ui/*` | shadcn primitives only; own/edit here; add variants via `cva`, don't break call sites |
| `web/src/components/*` | App chrome / composed widgets (`AppShell`, `AuthLayout`, `PasswordBox`) |
| `web/src/features/*/components/*` | Domain UI — compose `ui/*`, no parallel Button/Input/Dialog |
| `web/src/pages/*` | Route shells; keep thin |

- Prefer semantic utilities: `bg-card`, `text-muted-foreground`, `border-border`, `bg-primary`, `text-destructive`, `text-success`, `text-info`, `hover:bg-accent`
- Do **not** invent parallel controls with `var(--color-*)` in classNames; use theme utilities from `index.css` `@theme`
- Raw palette (`bg-blue-600`, `text-zinc-500`) only when no semantic token fits (rare status tones → prefer `Badge` variants)
- **Washes:** `accent` = voice interactive wash (hover / selected / queued). `secondary` = 6% ink|white **resting** wash (tabs track, read-only, notes). Do **not** use `bg-muted` / `hover:bg-muted/*` for hover or selected rows — `--color-muted` is solid `#71717a`, not a soft fill. See `docs/design/TOKENS.md`.
- **Tables:** `TableRow` hover/selected = `bg-accent` (`components/ui/table.tsx`)
- **Fields:** rest `border-input`; hover `border-voice-border`; focus `ring` (voice). View-only uses native `readOnly` (`bg-secondary` wash on `Input` / `Textarea`). Do not `disabled` a field the user should still copy from. `readOnly` must not use the edit `focus-visible` ring (`read-only:focus-visible:ring-0`).

Adding UI: check `components/ui` first; if missing, `pnpm dlx shadcn@latest add <name>`. Never re-export a second `Button` / `Input` / `Dialog` from feature or auth helpers. Prefer composed helpers in `components/` for repeated stacks: `FormField`, `IconButton`.

- `SelectContent` defaults to **`position="popper"`** (dropdown **below** the trigger). Do not revert to Radix `item-aligned`. Popper chrome: `border-border` (+ `dark:border-white/10`), same as `DropdownMenuContent`. Bare `border` inherits ink and reads too dark.
- Prefer standard `sm` / `md` / `lg` for micro chrome only (no one-off `min-[…px]:`)
- Session workspace: **content-based** `split` | `paged` in the shell (`session-layout.ts` + `useContainerWidth`) — do not gate panes on viewport `lg` or device names
- Leaf widgets take a `paged` / mode prop from the shell; they do not decide layout mode themselves
- **zh-HK copy split:** titles / labels / buttons stay all-Chinese — product & console names exempt (Instagram, S3, Meta, OAuth, API key, Token, tier names, Meta dashboard field names). Descriptions, hints, and running sentences may code-mix; HK loanwords (session, provider, orphan, prompt, load) are voice, not leftovers. Generic nouns inside a title still translate (計劃, not Plan).
