# Design tokens

> **Runtime today:** [`web/src/index.css`](../../web/src/index.css) — **harness desk applied** (IBM Plex Sans / Noto Sans HK, ink primary, voice accent).  
> **This doc:** inventory as-shipped (historical) + harness desk set now live in CSS.

---

## As-shipped (current CSS)

### Typography

| Token | Value |
|-------|-------|
| `--font-sans` | `"Inter", ui-sans-serif, system-ui, sans-serif` |

### Brand / action

| Token | Light (`@theme`) | Dark | Role |
|-------|------------------|------|------|
| `--color-primary` | `#6366f1` | *(same)* | Brand / primary actions |
| `--color-primary-foreground` | `#ffffff` | *(same)* | On-primary |
| `--color-ring` | `#6366f1` | *(same)* | Focus |
| `--color-destructive` | `#ef4444` | *(same)* | Danger |
| `--color-destructive-foreground` | `#b91c1c` | `#fca5a5` | Danger text |
| `--color-destructive-soft` | `rgb(239 68 68 / 0.1)` | same recipe | Soft danger |

Logo fill today: `#6366F1` (`web/public/logo.svg`).

### Surfaces

| Token | Light | Dark |
|-------|-------|------|
| `--color-background` | `#fafafa` | `#0a0a0b` |
| `--color-foreground` | `#18181b` | `#fafafa` |
| `--color-muted` / `--color-muted-foreground` | `#71717a` | muted `#71717a` / fg `#a1a1aa` |
| `--color-border` / `--color-input` | `#e4e4e7` | `#27272a` |
| `--color-card` / `--color-popover` | `#ffffff` | `#18181b` |
| `--color-accent` / `--color-secondary` | black @ 5% | white @ 5% |

---

## Harness desk (applied 2026-08)

Inter + SaaS indigo are gone; live values:

### Typography

| Token | Proposed |
|-------|----------|
| `--font-sans` | `"IBM Plex Sans", "Noto Sans HK", ui-sans-serif, system-ui, sans-serif` |

Load via `web/index.html` Google Fonts when applying.

### Brand / action

| Token | Light | Dark | Role |
|-------|-------|------|------|
| `--color-primary` | `#111113` | `#ececef` | Ink desk actions |
| `--color-primary-foreground` | `#fafafa` | `#111113` | On-primary |
| `--color-ring` | `#111113` | `#ececef` | Focus |
| `--color-destructive` | `#dc2626` | *(same)* | Danger |
| `--color-destructive-foreground` | `#991b1b` | `#fca5a5` | Danger text |
| `--color-destructive-soft` | `rgb(220 38 38 / 0.1)` | slightly stronger | Soft danger |
| `--color-voice` | `#c45c00` | `#f0a060` | Craft voice / action pulse (not shell fill) |
| `--color-voice-foreground` | `#ffffff` | `#111113` | On-voice |

Logo mark fill when applying: `#111113`.

### Surfaces

| Token | Light | Dark |
|-------|-------|------|
| `--color-background` | `#f3f3f4` | `#0c0c0e` |
| `--color-foreground` | `#111113` | `#f4f4f5` |
| `--color-muted-foreground` | `#5c5c66` | `#a1a1aa` |
| `--color-border` / `--color-input` | `#e0e0e4` | `#2a2a2e` |
| `--color-card` / `--color-popover` | `#ffffff` | `#161618` |
| `--color-accent` / `--color-secondary` | ink @ 6% | white @ 6% |

### Usage (when applied)

- Shell chrome → `primary`, surfaces, `muted-foreground`.
- Action trail / spitball / temp loading → `voice` (+ icons); do not recolor the whole app.
