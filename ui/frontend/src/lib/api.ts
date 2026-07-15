/** API client for the FastAPI backend. */

import type {
  ModelsResponse,
  Session,
  Message,
  HubSearchResult,
  ModelDetails,
  HardwareInfo,
  ModelUpdateInfo,
  ModelPreflight,
  Project,
  ComparisonModelInput,
  ApiKeyName,
  MaskedApiKeys,
  ApiKeyReveal,
  ApiKeySaveResult,
} from "./types";

// In dev mode, Vite proxies /api and /ws to localhost:8000.
// In the Tauri bundle, the frontend is served from the app itself
// (tauri://localhost), so we point directly at the sidecar on 8765.
const BASE = import.meta.env.DEV
  ? "/api"
  : "http://127.0.0.1:8765";

/** Build a WebSocket URL for a given backend path.
 *  Works both in dev (Vite proxy) and in the Tauri bundle. */
export function wsUrl(path: string): string {
  if (import.meta.env.DEV) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}${path}`;
  }
  return `ws://127.0.0.1:8765${path}`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = body.detail;
    const message = typeof detail === "string"
      ? detail
      : detail && typeof detail === "object" && "message" in detail
        ? String(detail.message)
        : `HTTP ${res.status}`;
    throw new Error(message);
  }
  return res.json();
}

// ── Models ──────────────────────────────────────────────────────────────

export const models = {
  list: () => request<ModelsResponse>("/models"),

  current: () =>
    request<{ loaded: boolean; model_id?: string; backend?: string; revision?: string | null; status?: string }>(
      "/models/current"
    ),

  load: (model_id: string, backend?: string, revision?: string | null) =>
    request<{ status: string; model: { model_id: string; backend: string; revision: string | null } }>(
      "/models/load",
      { method: "POST", body: JSON.stringify({ model_id, backend, revision }) }
    ),

  preflight: (input: {
    model_id: string;
    backend?: "mlx" | "hf";
    revision?: string | null;
  }) => request<ModelPreflight>("/models/preflight", {
    method: "POST",
    body: JSON.stringify(input),
  }),

  unload: () =>
    request<{ status: string }>("/models/unload", { method: "POST" }),

  search: (opts: {
    q?: string;
    sort?: "downloads" | "likes" | "lastModified" | "trending";
    backend?: "all" | "mlx" | "hf";
    limit?: number;
  } = {}) => {
    const p = new URLSearchParams();
    if (opts.q) p.set("q", opts.q);
    if (opts.sort) p.set("sort", opts.sort);
    if (opts.backend) p.set("backend", opts.backend);
    if (opts.limit) p.set("limit", String(opts.limit));
    return request<{ results: HubSearchResult[]; error?: string }>(
      `/models/search?${p.toString()}`
    );
  },

  details: (modelId: string) => {
    const [owner, repo] = modelId.split("/");
    return request<ModelDetails>(`/models/${owner}/${repo}/details`);
  },

  /** Delete a model from the HF cache. Returns freed_bytes. */
  deleteCache: (modelId: string) => {
    const [owner, repo] = modelId.split("/");
    return request<{ status: string; freed_bytes: number }>(
      `/models/cache/${owner}/${repo}?confirm=true`,
      { method: "DELETE" }
    );
  },

  /** Returns list of cached models + whether each has a newer commit on Hub. */
  updates: () => request<ModelUpdateInfo[]>("/models/updates"),
};

// ── System ──────────────────────────────────────────────────────────────

export const system = {
  hardware: () => request<HardwareInfo>("/system/hardware"),
};

// ── Preferences ─────────────────────────────────────────────────────────

export const prefs = {
  get: () =>
    request<{ hub_search_enabled: boolean }>("/settings/prefs"),

  setHubSearch: (enabled: boolean) =>
    request<{ status: string; hub_search_enabled: boolean }>(
      "/settings/hub-search",
      { method: "POST", body: JSON.stringify({ enabled }) }
    ),
};

export const apiKeys = {
  list: () => request<MaskedApiKeys>("/settings/keys"),

  reveal: (key: ApiKeyName) =>
    request<ApiKeyReveal>("/settings/keys/reveal", {
      method: "POST",
      body: JSON.stringify({ key }),
    }),

  save: (key: ApiKeyName, value: string) =>
    request<ApiKeySaveResult>("/settings/keys", {
      method: "POST",
      body: JSON.stringify({ key, value }),
    }),
};

// ── Projects and sessions ──────────────────────────────────────────────

export const projects = {
  list: () => request<Project[]>("/projects"),

  get: (id: string) => request<Project>(`/projects/${id}`),

  create: (name: string) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
};

export const sessions = {
  list: (
    limit = 50,
    offset = 0,
    filters: { project_id?: string; is_compare?: boolean } = {}
  ) => {
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (filters.project_id) params.set("project_id", filters.project_id);
    if (filters.is_compare !== undefined) {
      params.set("is_compare", String(filters.is_compare));
    }
    return request<Session[]>(`/sessions?${params.toString()}`);
  },

  get: (id: string) => request<Session>(`/sessions/${id}`),

  create: (
    title = "New session",
    is_compare = false,
    project_id?: string,
    models: ComparisonModelInput[] = []
  ) =>
    request<Session>("/sessions", {
      method: "POST",
      body: JSON.stringify({ title, is_compare, project_id, models }),
    }),

  delete: (id: string) =>
    request<{ status: string }>(`/sessions/${id}`, { method: "DELETE" }),

  update: (id: string, title: string) =>
    request<{ status: string }>(`/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),

  fork: (id: string, from_position: number) =>
    request<Session>(`/sessions/${id}/fork`, {
      method: "POST",
      body: JSON.stringify({ from_position }),
    }),

  messages: (id: string, limit = 1000, offset = 0) =>
    request<Message[]>(`/sessions/${id}/messages?limit=${limit}&offset=${offset}`),

  search: (query: string) =>
    request<Session[]>(`/sessions/search?q=${encodeURIComponent(query)}`),
};
