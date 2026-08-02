# Architecture Decision Records

Immutable-ish product/architecture decisions. STATUS may summarize; **ADRs are the durable record**.

| ID | Title | Status |
|----|-------|--------|
| [0001](./0001-preview-canonical-draft.md) | Preview Mode canonical draft | Accepted |
| [0002](./0002-rest-source-of-truth-sse-enhancement.md) | REST SSOT; SSE enhancement | Accepted |
| [0003](./0003-confirm-without-llm.md) | Confirm / publish without LLM | Accepted |
| [0004](./0004-stop-discard-and-image-resume.md) | Stop discards turn; explicit image resume | Accepted |

## Format

Each ADR: Context → Decision → Consequences. To reverse a decision, add a new ADR that **supersedes** the old one; do not silently rewrite history.
