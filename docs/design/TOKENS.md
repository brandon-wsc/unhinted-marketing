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
| `--color-ring` | `#a9580f` | `#f49d5f` | Keyboard / field focus — **alias of `voice`** (not `info`) |
| `--color-destructive` | `#ee3c37` | *(same)* | Danger |
| `--color-destructive-foreground` | `#9a1d1b` | `#fca79c` | Danger text |
| `--color-destructive-soft` | solid @ **10%** | solid @ **12%** | Soft danger |
| `--color-success` | `#16a34a` | *(same)* | Success |
| `--color-success-foreground` | `#1d6531` | `#94d29f` | Success text |
| `--color-success-soft` | solid @ **10%** | solid @ **12%** | Soft success |
| `--color-info` | `#4f83ee` | *(same)* | Informational (not brand) |
| `--color-info-foreground` | `#345290` | `#a0c0ff` | Info text |
| `--color-info-soft` | solid @ **10%** | solid @ **12%** | Soft info |
| `--color-voice` | `#a9580f` | `#f49d5f` | Craft + interaction pulse (not shell fill) |
| `--color-voice-foreground` | `#ffffff` | `#111113` | On-voice |
| `--color-voice-soft` | solid @ **10%** | solid @ **12%** | Craft wash — hover fill, running rows |
| `--color-voice-border` | `#dcbda9` | `#7e6250` | Opaque craft hairline (same hue 55; not `voice/40`) |

Logo mark: rounded tile in `primary`, vessel in `primary-foreground`, voice diamond in the cup (`voice`). Dark inverts the tile (same tokens).

An `<img>` SVG can't inherit the app's JS-toggled `.dark` CSS variables (the repo theme does not follow the OS), so the mark is two baked files rather than inline paths in TSX:
- [`logo-light.svg`](../../web/public/logo-light.svg) / [`logo-dark.svg`](../../web/public/logo-dark.svg)
- **App** — `AppLogo` sets `<img src>` from the app theme
- **Favicon** — same files via two `rel="icon"` links with `prefers-color-scheme` (OS-driven; no extra combined SVG)

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
| `--color-accent` | voice @ **10%** | voice @ **12%** | **Interactive wash** — hover, selected, queued (alias of `voice-soft`) |
| `--color-accent-foreground` | `#a9580f` | `#f49d5f` | Text on accent (alias of `voice`) |
| `--color-secondary` | ink @ **6%** | white @ **6%** | **Resting wash** — tabs track, read-only, notes |
| `--color-secondary-foreground` | `#111113` | `#f4f4f5` | Text on secondary |

---

## Usage rules

- Shell chrome **at rest** → `primary`, surfaces, `muted-foreground`.
- Interaction (hover, focus, selected, queued) → **voice family**. `ring` and `accent` alias voice / voice-soft. Do not reuse ink/`primary` for field or keyboard rings — black-on-black (and light-on-light in dark) fails focus appearance. Resting field chrome stays `border-input`. Invalid stays `destructive`. `info` is **status only** (alerts), not focus.

Status solids (`success` / `destructive` / `info`) are **OKLCH-aligned** in [`web/src/index.css`](../../web/src/index.css): shared `--status-l`, default `--status-c`, danger-only `--danger-c`, hue knobs. Hex below is resolved sRGB for Penpot / humans. Primary and surfaces stay out of this ramp. Voice has its **own** L/C knobs (below) — it is used as `text-voice` on cards, so light L is darker than `--status-l` (status solids at 0.627 fail AA as small text). `ring` follows voice, not the status ramp.

| Token | Hex | OKLCH |
|-------|-----|--------|
| `success` | `#16a34a` | `L 0.627 · C 0.170 · h 149` |
| `destructive` | `#ee3c37` | `L 0.627 · C 0.215 · h 27` (`--danger-c`, not `--status-c`) |
| `info` | `#4f83ee` | `L 0.627 · C 0.170 · h 263` |
| `ring` | same as `voice` | alias — not info |
| `voice` (light) | `#a9580f` | `L 0.548 · C 0.130 · h 55` |
| `voice` (dark) | `#f49d5f` | `L 0.772 · C 0.130 · h 55` |
| `voice-border` (light) | `#dcbda9` | `L 0.820 · C 0.045 · h 55` |
| `voice-border` (dark) | `#7e6250` | `L 0.520 · C 0.045 · h 55` |

Foreground / soft for status are the same hues at `--status-fg-l` (darker) and `--status-soft-a` (10% light / 12% dark). Dark info chroma is capped (`--status-fg-c: 0.096`) so blue stays in sRGB. Do not pick Tailwind blue-600 (`#2563eb`) — it is darker and as chromatic as old red-600. Voice reuses `--status-soft-a` for `voice-soft`. `voice-border` is an opaque same-hue hairline — do not recreate it as `border-voice/40`.
- **Voice variations for active chrome** — hover hairline → `border-voice-border`; hover / selected wash → `bg-accent` (`voice-soft`); focus ring / strong field chrome → `ring` / `border-voice`; ink + icons → `text-voice`. Queued composer stack rests as `bg-card` + `border-voice-border` (waiting = tuck + icon); row hover uses `bg-accent`, never `bg-card/80` on a tinted fill. Do not mix info blue into interaction. Do not paint `bg-voice` (solid) on shell chrome. Primary / Confirm stay ink.
- Action trail / spitball / temp loading → `text-voice` / `bg-voice` (+ icons); running-row wash → `bg-voice-soft`; craft hairline → `border-voice-border`. Light `text-voice` on white is **5.13:1** (AA); on `--color-background` **4.63:1**. Hue 55 (amber), not danger 27.
- Confirmations → `success` (`Alert variant="success"`, `text-success`). Errors → `destructive`. Informational / privilege reminders → `info` (`Alert variant="info"`; status blue, not interaction). Do not paint primary buttons green.
- Prefer semantic utilities (`bg-card`, `text-muted-foreground`, `hover:bg-accent`) — no parallel palette in JSX.

### `muted` vs `accent` vs `secondary` (important)

| Intent | Use | Avoid |
|--------|-----|--------|
| Secondary **text** | `text-muted-foreground` | — |
| Solid muted mark | `text-muted` / rare `bg-muted` when a solid gray chip is intentional | — |
| Hover / selected / queued / interactive wash | `bg-accent`, `hover:bg-accent` | **`hover:bg-muted` / `bg-muted/50`** — `muted` is opaque `#71717a`, so `/50` reads as a heavy gray veil |
| Resting wash (tabs track, read-only, notes) | `bg-secondary` | `bg-accent` — that now tints voice |

**Table rows** (`components/ui/table.tsx`): `hover:bg-accent` · `data-[state=selected]:bg-accent`.

**Menus / nav pills:** same interactive wash (`hover:bg-accent`).

---

## Component notes (runtime)

| Surface | Token behavior |
|---------|----------------|
| `TableRow` | Voice-soft accent hover (not muted) |
| `SelectContent` | Popper below trigger; hairline `border-border` (not bare `border` / ink) |
| `Card` | Hairline `border-border` (not bare `border` / ink) — auth card |
| `Input` / `Textarea` / `Select` | Rest `border-input`. Hover `border-voice-border`. Focus `border-ring` + `ring-ring` (voice). **Select open** uses the same ring via `data-[state=open]` — click focus moves into the list, so `:focus-visible` on the trigger is not enough. **`::selection`:** do **not** author `color` / `background-color` (no `selection:bg-primary`, no `Highlight` / hex blues). CSS Pseudo-4: when those are unset, the UA uses its own highlight — Chrome wash, Safari/OS, Firefox each differ, and they follow light/dark themselves. Empty `::selection {}` is a bug (invisible highlight). Do not re-add shadcn’s `selection:*` on `Input`. **`readOnly`:** keep `border-input`, `bg-secondary` wash, `cursor-default` (textarea also `resize-none`). Copyable. **`disabled`:** `opacity-50` + not-allowed — use for true unavailable, not view-only. Do not paint read-only with `bg-muted`. |
| `Tabs` | `variant="pills"` (default): track `bg-secondary`; active trigger `bg-card` + shadow. `variant="line"`: transparent track + `border-b border-border`; active ink underline (`border-foreground`); hover `bg-secondary`. Products **Org \| Mine** → **line**; settings sidebar nav → default **pills**. |
| Composer card | Outer `rounded-2xl border-border bg-card`; hover `border-voice-border`; `focus-within:border-voice`. Inner textarea is borderless; send/stop icon row sits **below** the textarea (not overlaid). Queue stack tucks above the card ([ADR 0016](../adr/0016-queue-send-while-turn-in-flight.md)). |
| Products list | Click row → detail dialog lists full `profile` columns; table stays name/sku/status only |
| Import | Reject files with **> 50** columns (COLLECT); no silent truncate |
