# Design (in-repo)

> **Format:** docs + tokens only — no external design-tool dependency.  
> **Runtime CSS:** [`web/src/index.css`](../../web/src/index.css) `@theme` remains what the app paints.  
> **Primitives / layers:** [`.cursor/rules/web-ui-system.mdc`](../../.cursor/rules/web-ui-system.mdc)

## Authority

| Doc | Job |
|-----|-----|
| [BRIEF.md](./BRIEF.md) | Product visual personality + open style decisions |
| [TOKENS.md](./TOKENS.md) | Semantic token inventory (mirrors `index.css`; proposed deltas marked) |
| [SCREENS.md](./SCREENS.md) | Screen inventory for reverse-engineering today’s UI |

**Voice / copy craft** stays in [VOICE.md](../VOICE.md) — design docs own chrome and surfaces, not post captions.

## Change rule

1. Lock intent in BRIEF / TOKENS (and a STATUS Decision when shipping a new look).
2. Update `web/src/index.css` `@theme` (+ logo / fonts as needed).
3. Prefer semantic utilities (`bg-primary`, `text-muted-foreground`, …) — do not invent a parallel palette in JSX.
