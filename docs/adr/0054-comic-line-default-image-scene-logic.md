# ADR 0054 — Comic-line default image style; product scene logic

## Status

Accepted

## Context

`single` image plans defaulted to `"bright, contemporary, editorial"` and the `IMAGE_PLAN` prompt said nothing about visual language or prop placement. An MCP smoke (2026-10-25) produced a photoreal street shot that read wrong for the brand: sweat / wet-pavement shadows as anchors, a cyan glow on an iced drink, heat haze, and a cup floating in the foreground with no one holding it. `comic_4panel` already used clean-line HK comic art; `single` did not.

## Decision

- **Default visual language (both formats):** clean-line contemporary Hong Kong comic / illustration, natural daylight, flat natural colors — not photoreal, not cinematic. `SINGLE_STYLE` becomes `"clean line contemporary Hong Kong comic illustration, natural daylight, flat natural colors, not photoreal"`; `COMIC_STYLE` is unchanged.
- **Photoreal is opt-in.** Phone-photo / documentary / cinematic only when the brief or user explicitly asks (寫實、街拍、實拍、documentary, phone photo). No new `image_format` value — the planner says so in `style`.
- **Scene logic.** Every product / featured object needs an owner: prefer a character's hand holding it at chest/waist height. Never floating with no holder, never alone on the ground for placement. Heat: small damp on clothing OK; sweat stains / wet pavement are not anchors; no steam on iced drinks. `compose_generation_prompt` appends a one-line scene-logic rule whenever the plan has a prompt.
- **Default avoid list** (`image_format.default_avoid`) is merged into every plan the planner returns (case-insensitive dedupe, planner items first): floating / ground-only product, haze / fog / smoke / heat shimmer, teal-orange or amber↔cyan grade, glowing cyan on drinks, steam on iced drinks, sweat / wet pavement anchors, logos, watermarks, celebrity faces, dense text. Photoreal / film-grain bans are added unless `style` opts into photo.
- **Format switch:** going comic → single now keeps a comic line-art `style`; only `COMIC_STYLE` itself or grid / strip vocabulary is rewritten to `SINGLE_STYLE`. The legacy `"bright, contemporary, editorial"` still maps to `COMIC_STYLE` when switching to comic.

## Consequences

- `image_format` stickiness, the angle-card lock ([ADR 0030](./0030-image-format-in-bundled-gate.md)), the 起承轉合 arc, and ADR 0036 direction-change detection are unchanged. `ImagePlanOut` and the API contracts are unchanged.
- Regenerating an older stored plan also gets the scene-logic line, because it is added at compose time.
- Photo opt-in is read from the plan `style` with a regex that ignores negations ("not photoreal"). A planner that asks for photoreal without saying so in `style` still gets the photoreal bans.
