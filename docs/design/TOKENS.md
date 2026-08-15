# Design tokens

> **Runtime SSOT:** [`web/src/index.css`](../../web/src/index.css) `@theme` + `.dark` overrides.  
> **Harness desk applied** (2026-08): IBM Plex Sans / Noto Sans HK, ink primary, voice accent.  
> Historical Inter + indigo palette removed from CSS — do not reintroduce.

---

## Typography

| Token | Value |
|-------|-------|
| `--font-sans` | `"IBM Plex Sans", "Noto Sans HK", ui-sans-serif, system-ui, sans-serif` |

Loaded via `web/index.html` Google Fonts.

---

## Brand / action

| Token | Light | Dark | Role |
|-------|-------|------|------|
| `--color-primary` | `#111113` | `#ececef` | Ink desk actions |
| `--color-primary-foreground` | `#fafafa` | `#111113` | On-primary |
| `--color-ring` | `#4f83ee` | *(same)* | Keyboard / field focus — same as `info` |
| `--color-destructive` | `#ee3c37` | *(same)* | Danger |
| `--color-destructive-foreground` | `#9a1d1b` | `#fca79c` | Danger text |
| `--color-destructive-soft` | solid @ **10%** | solid @ **12%** | Soft danger |
| `--color-success` | `#16a34a` | *(same)* | Success |
| `--color-success-foreground` | `#1d6531` | `#94d29f` | Success text |
| `--color-success-soft` | solid @ **10%** | solid @ **12%** | Soft success |
| `--color-info` | `#4f83ee` | *(same)* | Informational (not brand) |
| `--color-info-foreground` | `#345290` | `#a0c0ff` | Info text |
| `--color-info-soft` | solid @ **10%** | solid @ **12%** | Soft info |
| `--color-voice` | `#c45c00` | `#f0a060` | Craft voice / action pulse (not shell fill) |
| `--color-voice-foreground` | `#ffffff` | `#111113` | On-voice |

Logo mark fill: `#111113`.

---

## Surfaces

| Token | Light | Dark | Role |
|-------|-------|------|------|
| `--color-background` | `#f3f3f4` | `#0c0c0e` | App chrome |
| `--color-foreground` | `#111113` | `#f4f4f5` | Body text |
| `--color-muted` | `#71717a` | `#71717a` | **Solid mid-gray** — icons / secondary marks, **not** a wash |
| `--color-muted-foreground` | `#5c5c66` | `#a1a1aa` | Secondary text |
| `--color-border` / `--color-input` | `#e0e0e4` | `#2a2a2e` | Hairlines / inputs |
| `--color-card` / `--color-popover` | `#ffffff` | `#161618` | Elevated panels |
| `--color-accent` / `--color-secondary` | ink @ **6%** | white @ **6%** | **Subtle wash** — hover, selected, soft fills |
| `--color-accent-foreground` / `--color-secondary-foreground` | `#111113` | `#f4f4f5` | Text on accent/secondary |

---

## Usage rules

- Shell chrome → `primary`, surfaces, `muted-foreground`.
- Focus (`--color-ring`) → same OKLCH as `info`. Do not reuse ink/`primary` for field or keyboard rings — black-on-black (and light-on-light in dark) fails focus appearance. Resting field chrome stays `border-input`. Invalid stays `destructive`.

Status solids (`success` / `destructive` / `info` / `ring`) are **OKLCH-aligned** in [`web/src/index.css`](../../web/src/index.css): shared `--status-l`, default `--status-c`, danger-only `--danger-c`, hue knobs. Hex below is resolved sRGB for Penpot / humans. Voice, primary, and surfaces stay out of this ramp.

| Token | Hex | OKLCH |
|-------|-----|--------|
| `success` | `#16a34a` | `L 0.627 · C 0.170 · h 149` |
| `destructive` | `#ee3c37` | `L 0.627 · C 0.215 · h 27` (`--danger-c`, not `--status-c`) |
| `info` / `ring` | `#4f83ee` | `L 0.627 · C 0.170 · h 263` |

Foreground / soft are the same hues at `--status-fg-l` (darker) and `--status-soft-a` (10% light / 12% dark). Dark info chroma is capped (`--status-fg-c: 0.096`) so blue stays in sRGB. Do not pick Tailwind blue-600 (`#2563eb`) — it is darker and as chromatic as old red-600.
- Action trail / spitball / temp loading → `voice` (+ icons); do not recolor the whole app.
- Confirmations → `success` (`Alert variant="success"`, `text-success`). Errors → `destructive`. Informational / privilege reminders → `info` (`Alert variant="info"`; status blue, not shell brand). Do not paint primary buttons green.
- Prefer semantic utilities (`bg-card`, `text-muted-foreground`, `hover:bg-accent`) — no parallel palette in JSX.

### `muted` vs `accent` (important)

| Intent | Use | Avoid |
|--------|-----|--------|
| Secondary **text** | `text-muted-foreground` | — |
| Solid muted mark | `text-muted` / rare `bg-muted` when a solid gray chip is intentional | — |
| Hover / selected / soft panel wash | `bg-accent`, `hover:bg-accent` | **`hover:bg-muted` / `bg-muted/50`** — `muted` is opaque `#71717a`, so `/50` reads as a heavy gray veil |

**Table rows** (`components/ui/table.tsx`): `hover:bg-accent` · `data-[state=selected]:bg-accent`.

**Menus / nav pills:** same wash family (`hover:bg-accent`, settings nav `hover:bg-accent/60`).

---

## Component notes (runtime)

| Surface | Token behavior |
|---------|----------------|
| `TableRow` | Soft accent hover (not muted) |
| `SelectContent` | Popper below trigger; hairline `border-border` (not bare `border` / ink) |
| `Input` / `Textarea` | **`readOnly`:** keep `border-input`, `bg-accent` wash, `cursor-default` (textarea also `resize-none`). Copyable. **`disabled`:** `opacity-50` + not-allowed — use for true unavailable, not view-only. Do not paint read-only with `bg-muted`. |
| Products list | Click row → detail dialog lists full `profile` columns; table stays name/sku/status only |
| Import | Reject files with **> 50** columns (COLLECT); no silent truncate |
