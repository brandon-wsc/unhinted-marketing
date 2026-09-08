# Architecture Decision Records

Immutable-ish product/architecture decisions. STATUS may summarize; **ADRs are the durable record**.

| ID | Title | Status |
|----|-------|--------|
| [0001](./0001-preview-canonical-draft.md) | Preview Mode canonical draft | Accepted |
| [0002](./0002-rest-source-of-truth-sse-enhancement.md) | REST SSOT; SSE enhancement | Accepted |
| [0003](./0003-confirm-without-llm.md) | Confirm / publish without LLM | Accepted |
| [0004](./0004-stop-discard-and-image-resume.md) | Stop discards turn; explicit image resume | Accepted (§1 superseded by 0016) |
| [0005](./0005-platform-levels-and-llm-records.md) | Platform levels + LLM call records | Accepted |
| [0006](./0006-api-path-prefix-and-spa-proxy.md) | API `/api` prefix vs SPA same-origin proxy | Accepted (migration pending) |
| [0007](./0007-admin-trace-viewer.md) | Admin Trace viewer (node-steps + session) | Accepted |
| [0008](./0008-preview-images-append-only.md) | Append-only preview images + draft `media_ids` | Accepted |
| [0009](./0009-research-gate-and-tavily-ingest.md) | Unified intent + research gate; Tavily∪PG ingest | Accepted |
| [0010](./0010-org-membership-invites-and-shared-assets.md) | Org membership, invite links, shared-asset scope | Accepted (§4 amended by 0013; §2 by 0014) |
| [0011](./0011-knowledge-commit-without-llm.md) | Knowledge commit without LLM (K6 Approvals) | Accepted |
| [0013](./0013-invite-accept-replaces-bootstrap-org.md) | Invite accept replaces bootstrap solo org | Accepted (amended by 0015) |
| [0014](./0014-invite-public-preview.md) | Public invite preview (email + company name) | Accepted |
| [0015](./0015-invite-rehome-solo-products.md) | Solo-org invite accept rehomes products to Mine | Accepted |
| [0016](./0016-queue-send-while-turn-in-flight.md) | Queue send while a turn is in flight | Accepted |
| [0017](./0017-session-fork.md) | Session fork (branch a chat at an assistant message) | Accepted |
| [0018](./0018-recommended-questions-worker-graph.md) | Recommended questions worker graph + fill contract | Accepted |
| [0019](./0019-pydantic-ai-inner-harness.md) | Pydantic AI inner harness; session graph narrows to mode/lifecycle | Accepted |
| [0020](./0020-org-byok-keys-models-routing.md) | Org BYOK: provider keys, model registry, per-tier routing | Accepted (enum + Completions-only surface amended by 0021) |
| [0021](./0021-org-byok-native-gemini.md) | Org BYOK: native Gemini + Vertex Express | Accepted |
| [0022](./0022-real-publish-instagram.md) | Real publish: Instagram adapter, org social accounts, receipt status | Accepted |
| [0023](./0023-deployment-mode-flag.md) | Deployment mode flag (cloud vs on-prem) | Accepted |
| [0024](./0024-media-storage-local-and-s3.md) | Media storage: local on-prem, AWS S3 in cloud | Accepted |

## Format

Each ADR: Context → Decision → Consequences. To reverse a decision, add a new ADR that **supersedes** the old one; do not silently rewrite history.
