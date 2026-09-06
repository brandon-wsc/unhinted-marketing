/* AUTO-GENERATED from docs/contracts/publish-social-post-response.schema.json via json-schema-to-typescript — do not edit. */

export type ReceiptId = string;
export type Status = string;
export type ToolName = string;
export type IdempotencyKey = string;
export type Platform = string;
export type Permalink = string | null;
export type ErrorKind = string | null;

export interface PublishSocialPostResponse {
  receipt_id: ReceiptId;
  status: Status;
  tool_name?: ToolName;
  idempotency_key: IdempotencyKey;
  platform?: Platform;
  permalink?: Permalink;
  error_kind?: ErrorKind;
}
