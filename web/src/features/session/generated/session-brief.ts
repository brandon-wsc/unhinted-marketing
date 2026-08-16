/* AUTO-GENERATED from docs/contracts/session-brief.schema.json via json-schema-to-typescript — do not edit. */

export type CanDo = string[];
export type CannotDo = string[];
export type Angles = string[];
export type Persona = string | null;
export type Summary = string;

/**
 * Payload for `brief.updated` (matches session BriefOut / FE SessionBrief).
 */
export interface SessionBriefData {
  can_do: CanDo;
  cannot_do: CannotDo;
  angles: Angles;
  persona: Persona;
  summary: Summary;
}
