# Verify Unhinted — feature map

The repo's maintained verification source. A proof that drives one convenient entry point is incomplete when this map lists others — pick the features your change can touch.

| Feature | Scripted? | Needs |
|---------|-----------|-------|
| [first-run-setup](first-run-setup.md) | `verify.sh drive first-run-setup` | fresh run (unclaimed instance) |
| [session-workspace](session-workspace.md) | `verify.sh drive session-workspace` | `first-run-setup` drove first (leaves `state/auth.json`) |
| [session-chat](session-chat.md) | manual curl recipe | `OPENAI_API_KEY` (or org BYOK) passed through at launch |
| [confirm-publish](confirm-publish.md) | manual curl recipe | a session holding a draft — so `session-chat` first |
| [web-ui](web-ui.md) | manual recipe | vite dev + the verify API port caveats inside |

Drives write `evidence/<run-id>/<feature>/NN-step.json` — `{http_status, body}` per call. A feature file's `Gotchas` section records known precondition gaps; if a journey can't reach its end state on a fresh launch, report the failure and add the reason there — never weaken the journey to pass.
