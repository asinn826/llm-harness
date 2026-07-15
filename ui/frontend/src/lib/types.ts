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
  /** Older cached model IDs that this one supersedes — used to surface
   * "newer version available" hints on Recommended cards. */
  supersedes_cached?: string[];
}

/** Alias for clarity — the same shape, just a domain marker. */
export type RecommendedModel = ModelInfo;

export interface ModelsResponse {
  recommended: ModelInfo[];
  cached: ModelInfo[];
  current: string | null;
  current_backend: string | null;
  current_revision?: string | null;
}

export interface ModelPreflightError {
  code: string;
  message: string;
  retryable: boolean;
}

/** Executability verdict returned before any Hub model is installed or run. */
export interface ModelPreflight {
  model_id: string;
  backend: "mlx" | "hf";
  requested_revision: string | null;
  resolved_revision: string | null;
  access: "public" | "authorized" | "token_required" | "denied";
  compatible: boolean | null;
  compatibility_code: string;
  model_size_bytes: number;
  estimated_memory_bytes: number;
  available_memory_bytes: number;
  memory_budget_bytes?: number;
  memory_fit: "fits" | "tight" | "too_large" | "unknown";
  can_install: boolean;
  can_load: boolean;
  error: ModelPreflightError | null;
  runtime_available?: boolean;
  cache_status?: "missing" | "partial" | "complete";
  cached_bytes?: number;
  required_download_bytes?: number;
  available_disk_bytes?: number;
  disk_fit?: "fits" | "insufficient" | "unknown";
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
  resolved_revision?: string | null;
  readme_markdown: string;
}

/** Hardware info from GET /system/hardware */
export interface HardwareInfo {
  total_memory_bytes: number;
  available_memory_bytes: number;
  platform: string;
  is_apple_silicon: boolean;
}

export type ApiKeyName = "TAVILY_API_KEY" | "HF_TOKEN";

export type MaskedApiKeys = Record<ApiKeyName, string>;

export interface ApiKeyReveal {
  key: ApiKeyName;
  value: string;
}

export interface ApiKeySaveResult {
  status: string;
  unchanged?: boolean;
  masked: string;
}

/** One entry in GET /models/updates response */
export interface ModelUpdateInfo {
  id: string;
  has_update: boolean;
  local_sha: string | null;
  remote_sha: string | null;
}

/** State of an in-flight model load (lives in DownloadsContext). */
export type DownloadStatus = "downloading" | "loading" | "ready" | "error";

export interface DownloadState {
  modelId: string;
  backend: "mlx" | "hf";
  revision?: string | null;
  operation?: "install" | "load";
  status: DownloadStatus;
  progress: number; // 0..1
  message: string;
  error?: string;
  startedAt: number;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  is_default: number;
  session_count: number;
  comparison_count: number;
}

export interface ComparisonModel {
  session_id: string;
  position: number;
  model_id: string;
  backend: "mlx" | "hf" | null;
  revision: string | null;
}

export interface ComparisonModelInput {
  model_id: string;
  backend?: "mlx" | "hf" | null;
  revision?: string | null;
}

export interface Session {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  is_compare: number | boolean;
  project_id: string;
  message_count?: number;
  models: string[];
  comparison_models: ComparisonModel[];
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
  | { type: "token"; data: string; session_id?: string; model_id?: string; index?: number }
  | { type: "tool_call"; tool: string; args: Record<string, unknown>; needs_confirmation: boolean; session_id?: string; model_id?: string; index?: number }
  | { type: "tool_result"; result: string; tool: string; args?: Record<string, unknown>; session_id?: string; model_id?: string; index?: number }
  | { type: "done"; response: string; tokens?: number; time_ms?: number; session_id?: string }
  | { type: "session_created"; session_id: string; title?: string; project_id?: string }
  | { type: "error"; message: string }
  | { type: "title_updated"; session_id: string; title: string }
  // Compare-specific
  | { type: "model_start"; session_id: string; model_id: string; index: number }
  | { type: "model_done"; session_id: string; model_id: string; index: number; response: string; tokens: number; time_ms: number }
  | { type: "compare_done"; session_id: string };

/** WebSocket message types (client → server) */
export type WSClientMessage =
  | {
      type: "message";
      content: string;
      session_id?: string;
      model_id?: string;
      models?: Array<string | ComparisonModelInput>;
      project_id?: string;
    }
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
