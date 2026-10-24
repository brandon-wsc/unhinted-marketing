# ADR 0052 — UI locales zh-TW / zh-CN; UI locale independent of draft voice

## Status

Accepted

## Context

The SPA shipped with two locale catalogs — `zh-HK` (default, spoken 粵語 chrome) and `en` — and the 2026-08-22 STATUS decision locked "UI + draft locale is `zh-HK` only". That coupling was fine while the only users were the HK team. Operators in Taiwan / mainland teams need a written-register console, but draft voice is a product contract ([VOICE.md](../VOICE.md)): captions, hashtags, CTA, and pipeline LLM output stay HK Cantonese Traditional no matter who is looking at the screen.

## Decision

- `SUPPORTED_LOCALES` grows to `["zh-HK", "zh-TW", "zh-CN", "en"]`; default stays `zh-HK`. The pick persists in `localStorage["unhinted-locale"]` and mirrors to `document.documentElement.lang`.
- `zh-TW` and `zh-CN` are **written-register (書面語)** catalogs — the spoken 粵語 chrome is rewritten, not character-mapped from `zh-HK.json`. Key trees stay identical across all four catalogs; `locales.test.ts` enforces parity.
- **UI locale ≠ draft voice.** Switching the picker changes chrome only. Company Voice `locale` / `voice_pack` defaults, VOICE.md, and `internal/session/prompts.py` are untouched; a session started under any UI locale still produces HK Cantonese Traditional drafts.
- Noto Sans SC joins the Google Fonts link and replaces Noto Sans HK in `--font-sans` under `html[lang="zh-CN"]`; other locales keep Noto Sans HK.
- Locale-conditional formatting follows `i18n.language` (date pickers, admin timestamps); worked-duration units pick Traditional or Simplified hour glyphs to match.
- Picker labels: 繁體中文（香港）/ 繁體中文（書面）/ 简体中文 / English — label wording is cosmetic and does not need a superseding ADR.

## Consequences

- New UI strings must land in all four catalogs in the same PR — the key-parity test enforces presence; register quality is on the author.
- A user on a 書面語 UI still gets Cantonese drafts; support copy should not promise otherwise.
- No `yue` catalog — the spoken register stays a layer inside `zh-HK`, per the 2026-08-22 decision. This ADR only decouples UI chrome from draft voice.
