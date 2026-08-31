/* AUTO-GENERATED from docs/contracts/preview-updated.schema.json via json-schema-to-typescript — do not edit. */

export type Revision = number;
export type ApprovalToken = string;
export type ImageUrl = string | null;
export type Id = string;
export type Url = string | null;
export type Format = ("single" | "comic_4panel") | string;
export type Role = string;
export type Seq = number;
export type Status = string;
export type Media = PreviewMediaItem[];
export type Caption = string;
/**
 * @maxItems 40
 */
export type Hashtags = string[];
export type Cta = string;
export type Platform = string;
export type SourceSignalIds = string[];
export type SignalId = string;
export type Source = string;
export type Title = string;
export type Url1 = string | null;
export type Excerpt = string | null;
export type Sources = CitedSignal[];

/**
 * Payload for SSE / turn event `preview.updated`.
 */
export interface PreviewUpdatedData {
  revision: Revision;
  approval_token: ApprovalToken;
  image_url: ImageUrl;
  media: Media;
  copy: DraftCopy;
  platform: Platform;
  source_signal_ids: SourceSignalIds;
  sources: Sources;
}
/**
 * One append-only image version referenced by a draft (ADR 0008).
 *
 * This interface was referenced by `PreviewUpdatedData`'s JSON-Schema
 * via the `definition` "PreviewMediaItem".
 */
export interface PreviewMediaItem {
  id: Id;
  url: Url;
  plan: Plan;
  format: Format;
  role: Role;
  seq: Seq;
  status: Status;
}
export interface Plan {
  [k: string]: unknown;
}
/**
 * Shared post copy across preview skins (ADR 0001).
 *
 * This interface was referenced by `PreviewUpdatedData`'s JSON-Schema
 * via the `definition` "DraftCopy".
 */
export interface DraftCopy {
  caption: Caption;
  hashtags: Hashtags;
  cta: Cta;
}
/**
 * User-facing HK market signal card for session source-trace links (ADR 0022).
 *
 * This interface was referenced by `PreviewUpdatedData`'s JSON-Schema
 * via the `definition` "CitedSignal".
 */
export interface CitedSignal {
  signal_id: SignalId;
  source: Source;
  title: Title;
  url: Url1;
  excerpt: Excerpt;
}
