/* AUTO-GENERATED from docs/contracts/publish-social-post-request.schema.json via json-schema-to-typescript — do not edit. */

export type SessionId = string;
export type ApprovalToken = string;
export type IdempotencyKey = string;
export type Platform = string;
export type Caption = string;
/**
 * @maxItems 40
 */
export type Hashtags = string[];
export type Cta = string;
export type ImageUrl = string | null;
export type Revision = number;

/**
 * Confirm-handler adapter input only — never invoked from LangGraph (ADR 0003).
 */
export interface PublishSocialPostRequest {
  session_id: SessionId;
  approval_token: ApprovalToken;
  idempotency_key: IdempotencyKey;
  platform?: Platform;
  copy: DraftCopy;
  image_url?: ImageUrl;
  revision: Revision;
}
/**
 * Shared post copy across preview skins (ADR 0001).
 *
 * This interface was referenced by `PublishSocialPostRequest`'s JSON-Schema
 * via the `definition` "DraftCopy".
 */
export interface DraftCopy {
  caption: Caption;
  hashtags: Hashtags;
  cta: Cta;
}
