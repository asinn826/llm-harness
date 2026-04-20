/** Shared types mirroring the backend API. */

export interface ModelInfo {
  id: string;
  name: string;
  backend: "mlx" | "hf";
  size?: string;
  heat?: "Cool" | "Warm" | "Hot";
  quality?: string;
  is_cached: boolean;
  is_loaded: boolean;
}

export interface ModelsResponse {
  recommended: ModelInfo[];
  cached: ModelInfo[];
  current: string | null;
  current_backend: string | null;
}

export interface Session {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  is_compare: number;
  message_count?: number;
  models?: string[];
}

export interface Message {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  model_id: string | null;
  tool_name: string | null;
  tool_args: Record<string, unknown> | null;
  tokens_generated: number | null;
  generation_time_ms: number | null;
  created_at: string;
  position: number;
}

/** WebSocket message types (server → client) */
export type WSServerMessage =
  | { type: "token"; data: string }
  | { type: "tool_call"; tool: string; args: Record<string, unknown>; needs_confirmation: boolean }
  | { type: "tool_result"; result: string; tool: string; args: Record<string, unknown> }
  | { type: "done"; response: string; tokens?: number; time_ms?: number; session_id?: string }
  | { type: "session_created"; session_id: string; title?: string }
  | { type: "error"; message: string }
  | { type: "title_updated"; session_id: string; title: string }
  // Compare-specific
  | { type: "model_start"; model_id: string; index: number }
  | { type: "model_done"; model_id: string; index: number; response: string; tokens: number; time_ms: number }
  | { type: "compare_done"; session_id: string };

/** WebSocket message types (client → server) */
export type WSClientMessage =
  | { type: "message"; content: string; session_id?: string; model_id?: string }
  | { type: "tool_response"; approved: boolean | string };

/** Model color assignment — persistent across the app */
export const MODEL_COLORS: Record<string, string> = {};
const COLOR_PALETTE = [
  "#7c6fef", // violet
  "#4ade80", // green
  "#f97316", // orange
  "#06b6d4", // cyan
  "#ec4899", // pink
  "#eab308", // yellow
  "#8b5cf6", // purple
  "#14b8a6", // teal
];
let _colorIndex = 0;

export function getModelColor(modelId: string): string {
  if (!MODEL_COLORS[modelId]) {
    MODEL_COLORS[modelId] = COLOR_PALETTE[_colorIndex % COLOR_PALETTE.length];
    _colorIndex++;
  }
  return MODEL_COLORS[modelId];
}
