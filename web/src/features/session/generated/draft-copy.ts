/* AUTO-GENERATED from docs/contracts/draft-copy.schema.json via json-schema-to-typescript — do not edit. */

export type Caption = string;
/**
 * @maxItems 40
 */
export type Hashtags = string[];
export type Cta = string;

/**
 * Shared post copy across preview skins (ADR 0001).
 */
export interface DraftCopy {
  caption: Caption;
  hashtags: Hashtags;
  cta: Cta;
}
