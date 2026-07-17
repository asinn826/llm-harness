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

export type ApiErrorKind =
  | "offline"
  | "timeout"
  | "unauthorized"
  | "forbidden"
  | "not-found"
  | "request"
  | "server";

export class ApiError extends Error {
  kind: ApiErrorKind;
  status?: number;
  retryable: boolean;
  detail?: string;

  constructor(
    kind: ApiErrorKind,
    message: string,
    options: { status?: number; retryable?: boolean; detail?: string } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status;
    this.retryable = options.retryable ?? false;
    this.detail = options.detail;
  }
}

const OFFLINE_MESSAGE = "Couldn’t connect to Harness. Make sure the local service is running, then try again.";

export function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) {
    if (/failed to fetch|networkerror|load failed/i.test(error.message)) {
      return OFFLINE_MESSAGE;
    }
    return error.message || fallback;
  }
  return fallback;
}

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
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
      signal: controller.signal,
    });
  } catch (error) {
    if (controller.signal.aborted) {
      throw new ApiError(
        "timeout",
        "Harness took too long to respond. Try again.",
        { retryable: true },
      );
    }
    throw new ApiError("offline", OFFLINE_MESSAGE, {
      retryable: true,
      detail: error instanceof Error ? error.message : undefined,
    });
  } finally {
    window.clearTimeout(timeout);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = body.detail;
    const detailMessage = typeof detail === "string"
      ? detail
      : detail && typeof detail === "object" && "message" in detail
        ? String(detail.message)
        : `HTTP ${res.status}`;
    if (res.status === 401) {
      throw new ApiError("unauthorized", "Your connection is no longer authorized. Reconnect and try again.", {
        status: res.status,
        detail: detailMessage,
      });
    }
    if (res.status === 403) {
      throw new ApiError("forbidden", "Harness doesn’t have permission to complete this action.", {
        status: res.status,
        detail: detailMessage,
      });
    }
    if (res.status === 404) {
      throw new ApiError("not-found", detailMessage, { status: res.status });
    }
    if (res.status >= 500) {
      throw new ApiError(
        "server",
        res.status === 502 || res.status === 503 || res.status === 504
          ? "The Harness service is temporarily unavailable. Try again."
          : "Harness couldn’t complete the request. Try again.",
        { status: res.status, retryable: true, detail: detailMessage },
      );
    }
    throw new ApiError("request", detailMessage, { status: res.status });
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
  health: () => request<{ status: string }>("/health"),
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
