# Unhinted — Visual brief

> **Status:** Positioning locked. Runtime tokens + localized craft pulse applied (`web/src/index.css`, session / auth / Voice settings).
> Penpot visual SSOT: see [README.md](./README.md) page inventory.

## North star

**Reliable tools that harness unhinged creative energy.**
Product name stays **Unhinted**. "Unhinged" describes the copy kid / craft voice — never the company wordmark or shell chrome.

Metaphor: a professional studio desk harnessing a chaotic copy kid. The kid is not the product; the harness is.

## Core tension (asymmetric)

- **RELIABLE holds the reins**: more area, default tone, first impression.
- **UNHINGED is the pulse**: interaction (hover, focus, queued) and where a person or agent is speaking.

Do NOT split the UI 50/50 visually (half neon / half corporate). Shell stays normal **at rest**; the voice pulse is localized to active chrome and craft copy.

| Layer | Job |
|-------|-----|
| **Shell** | Tech-product standard (shadcn structure): scannable desk — header, history, composer, preview, Confirm |
| **Craft** | Chat editor voice + agent action trail — spitball copy, special icons, temp loading filler (e.g. 「幫緊你…」 “working on it”) |

## Shell — must read as a big-tech product desk

Structure: shadcn / Radix + Tailwind semantic tokens. Scannable regions: header, history, chat, preview, Confirm.

Shell MUST:

- Use neutral surfaces + one primary; clear type hierarchy; familiar controls
- Keep errors, Stop, Confirm, admin in short, accurate, non-meme copy
- Feel like a tool users can trust to publish from — not a meme app or marketing landing

Shell MUST NOT:

- Purple/indigo SaaS default as brand identity
- Cream + terracotta + display serif "AI poster" kits
- Broadsheet newspaper chrome
- Neon, Liquid Glass, glow stacks, glassmorphism piles, sparkle loaders
- Emoji-as-UI; vague booster English ("Crafting your narrative…")
- Browser-only tricks (Chromium SVG backdrop refraction, `-apple-visual-effect`) for core chrome

Borrow SPIRIT from Material / Fluent / restrained HIG — not cosplay any one OS.

**Screenshot test:** cover chat + action spitball in a screenshot — the app must still read as a reliable media tool.

## Craft — where personality lives

ALLOWED (localized):

- Interaction pulse: hover / focus / queued / selected — voice hairline, wash, and ring (shell stays ink **at rest**)
- Chat editor-voice tone (see [VOICE.md](../VOICE.md) for captions — assistant shell voice stays clear/warm, not meme-account)
- Agent action trail: short spitball line + distinctive icon per step
- Empty states / recommended-question cards: light attitude
- Temporary loading filler ONLY when no real progress yet (e.g. 「幫緊你幫緊你」 “on it, on it”) — yield immediately when `agent.progress` arrives
- Login/register: orderly form; at most ONE corner craft signal — never half-viewport unhinged

FORBIDDEN on craft surfaces:

- Confirm / publish gate spitball
- Recoloring the entire app to "fun"
- Action rows that become an unreadable meme wall (legibility first, spitball second)

## Geography

Brand story is global (control × chaos). Do NOT rely on HK postcard clichés (neon, tea-restaurant kits, street-sign fluoro) for shell theme. HK Cantonese craft belongs in output copy (VOICE), not map decoration.

## Motion

At most 2–3 intentional motions (send, preview ready, interrupt) — no decorative particles.

## Hard product boundaries (never violate)

- Confirm ≠ chat — publish only via UI Confirm + `approval_token`
- REST is source of truth; SSE is enhancement
- LangGraph owns session LLM zone only

Craft may sound casual; the publish gate stays serious.

## Shell reference

Structure ≈ shadcn / big-tech product UI. Brand difference = **ink primary + IBM Plex / Noto Sans HK + voice accent** (see [TOKENS.md](./TOKENS.md)).

## When unsure

Default to MORE reliable shell, LESS decorative brand. Add personality only where someone is talking.
