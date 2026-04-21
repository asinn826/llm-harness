/** Shared types mirroring the backend API. */

export interface ModelInfo {
  id: string;
  name: string;
  author?: string;
  backend: "mlx" | "hf";
  size?: string;
  size_bytes?: number;
  size_label?: string;
  heat?: "Cool" | "Warm" | "Hot";
  quality?: string;
  is_cached: boolean;
  is_loaded: boolean;
  // Enriched fields (recommended + cached) — see recommended_models.json schema
  parameters?: string;
  quantization?: string;
  context_window?: number;
  description?: string;
  license?: string;
  tags?: string[];
  hf_url?: string;
  tool_use_tier?: "verified" | "likely" | "unknown";
  last_used?: number; // unix timestamp
}

/** Alias for clarity — the same shape, just a domain marker. */
export type RecommendedModel = ModelInfo;

export interface ModelsResponse {
  recommended: ModelInfo[];
  cached: ModelInfo[];
  current: string | null;
  current_backend: string | null;
}

/** A single Hub search hit returned by GET /models/search. */
export interface HubSearchResult {
  id: string;
  author: string;
  name: string;
  downloads: number;
  likes: number;
  last_modified: string | null;
  tags: string[];
  pipeline_tag: string | null;
  gated: boolean;
  backend_hint: "mlx" | "hf";
  tool_use_tier: "verified" | "likely" | "unknown";
  is_cached: boolean;
  compatible: boolean;
}

/** Detailed info returned by GET /models/{owner}/{repo}/details */
export interface ModelDetails {
  id: string;
  description: string;
  tags: string[];
  license: string | null;
  downloads: number;
  likes: number;
  gated: boolean;
  pipeline_tag: string | null;
  model_size_bytes: number;
  last_modified: string | null;
  readme_markdown: string;
}

/** State of an in-flight model load (lives in DownloadsContext). */
export type DownloadStatus = "downloading" | "loading" | "ready" | "error";

export interface DownloadState {
  modelId: string;
  backend: "mlx" | "hf";
  status: DownloadStatus;
  progress: number; // 0..1
  message: string;
  error?: string;
  startedAt: number;
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
  "#5088f7", // blue (matches accent)
  "#3ecf71", // green
  "#e5a820", // amber
  "#c9555a", // red
  "#2aadad", // teal
  "#b07ce0", // lavender
  "#e08c4a", // orange
  "#6ba3a3", // sage
];
let _colorIndex = 0;

export function getModelColor(modelId: string): string {
  if (!MODEL_COLORS[modelId]) {
    MODEL_COLORS[modelId] = COLOR_PALETTE[_colorIndex % COLOR_PALETTE.length];
    _colorIndex++;
  }
  return MODEL_COLORS[modelId];
}
