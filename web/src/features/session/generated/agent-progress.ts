/* AUTO-GENERATED from docs/contracts/agent-progress.schema.json via json-schema-to-typescript — do not edit. */

export type Node = string;
export type ModelTier = string | null;
export type Model = string | null;

/**
 * Payload for `agent.progress`.
 */
export interface AgentProgressData {
  node: Node;
  model_tier: ModelTier;
  model: Model;
}
