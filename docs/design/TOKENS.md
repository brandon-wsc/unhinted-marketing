# Design tokens

> **As-shipped source:** [`web/src/index.css`](../../web/src/index.css) `@theme` + light/dark overrides.  
> **Rule:** document here → change CSS → consume via semantic Tailwind utilities (`bg-background`, `text-primary`, …).  
> Values below are **as-is** unless marked **Proposed**.

---

## Typography

| Token | As-is | Notes |
|-------|-------|-------|
| `--font-sans` | `"Inter", ui-sans-serif, system-ui, sans-serif` | Generic SaaS stack — **Proposed:** replace with expressive brand + CJK-capable pair when direction locks |

No separate display / mono tokens yet.

---

## Brand / action

| Token | Light (default `@theme`) | Dark (`:root.dark`) | Role |
|-------|--------------------------|---------------------|------|
| `--color-primary` | `#6366f1` | *(same — not overridden)* | Brand / primary actions |
| `--color-primary-foreground` | `#ffffff` | *(same)* | On-primary text |
| `--color-ring` | `#6366f1` | *(same)* | Focus ring |
| `--color-destructive` | `#ef4444` | *(same)* | Danger actions |
| `--color-destructive-foreground` | `#b91c1c` | `#fca5a5` | Danger text |
| `--color-destructive-soft` | `rgb(239 68 68 / 0.1)` | same alpha recipe | Soft danger fill |

**Proposed (direction A, not applied):** replace indigo primary with ink + one hot accent; keep destructive red family unless accent is chilli-red (then differentiate danger).

Logo fill today: `#6366F1` in [`web/public/logo.svg`](../../web/public/logo.svg).

---

## Surfaces (light)

| Token | Value | Typical utility |
|-------|-------|-----------------|
| `--color-background` | `#fafafa` | `bg-background` |
| `--color-foreground` | `#18181b` | `text-foreground` |
| `--color-muted` | `#71717a` | — |
| `--color-muted-foreground` | `#71717a` | `text-muted-foreground` |
| `--color-border` | `#e4e4e7` | `border-border` |
| `--color-card` | `#ffffff` | `bg-card` |
| `--color-card-foreground` | `#18181b` | `text-card-foreground` |
| `--color-accent` | `rgb(0 0 0 / 0.05)` | `bg-accent` |
| `--color-accent-foreground` | `#18181b` | `text-accent-foreground` |
| `--color-secondary` | `rgb(0 0 0 / 0.05)` | `bg-secondary` |
| `--color-secondary-foreground` | `#18181b` | `text-secondary-foreground` |
| `--color-popover` | `#ffffff` | `bg-popover` |
| `--color-popover-foreground` | `#18181b` | `text-popover-foreground` |
| `--color-input` | `#e4e4e7` | `border-input` / input chrome |
| `--shadow-color` | `rgb(0 0 0 / 0.08)` | Auth card shadow (inline) |

## Surfaces (dark)

| Token | Value |
|-------|-------|
| `--color-background` | `#0a0a0b` |
| `--color-foreground` | `#fafafa` |
| `--color-muted` | `#71717a` |
| `--color-muted-foreground` | `#a1a1aa` |
| `--color-border` | `#27272a` |
| `--color-card` | `#18181b` |
| `--color-card-foreground` | `#fafafa` |
| `--color-accent` | `rgb(255 255 255 / 0.05)` |
| `--color-accent-foreground` | `#fafafa` |
| `--color-secondary` | `rgb(255 255 255 / 0.05)` |
| `--color-secondary-foreground` | `#fafafa` |
| `--color-popover` | `#18181b` |
| `--color-popover-foreground` | `#fafafa` |
| `--color-input` | `#27272a` |
| `--shadow-color` | `rgb(0 0 0 / 0.35)` |

---

## Radius / density (implicit)

Not declared as `@theme` tokens yet. Controls use shadcn defaults (`rounded-md`, button `h-9`, etc. in `web/src/components/ui/*`). **Proposed:** add `--radius-*` when locking direction so chrome stays consistent across auth + session.

---

## How to evolve tokens

1. Edit the table here (mark **Proposed** → **Locked**).
2. Patch `web/src/index.css` `@theme` / dark overrides to match.
3. Keep JSX on semantic utilities; raw palette (`bg-blue-600`, …) only when no semantic token fits (rare status tones → prefer `Badge` variants).
