/**
 * DownloadsContext — app-wide state for in-flight model loads.
 *
 * Why this exists: model downloads need to survive navigation
 * (Chat ↔ Models) so both the Models page cards AND the sidebar
 * ModelSwitcher can reflect the same live progress. Local component
 * state loses this on unmount.
 *
 * Owns:
 * - `downloads`: Record keyed by modelId → DownloadState (progress, message)
 * - `currentModelId` / `currentBackend`: the one loaded model (singleton)
 * - A Map<modelId, WebSocket> for active sockets
 *
 * Exposes:
 * - startDownload(modelId, backend) — opens WS to /ws/models/load
 * - cancelDownload(modelId) — closes the WS (server-side load can't be
 *   cancelled mid-flight, but we stop listening and free the slot)
 * - refreshCurrent() — pulls /api/models/current
 * - subscribe(listener) — fire-and-forget notifications on completion/failure
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { DownloadState } from "../lib/types";
import { models as modelsApi } from "../lib/api";

export type DownloadEvent =
  | { type: "completed"; modelId: string; backend: string }
  | { type: "failed"; modelId: string; error: string };

interface DownloadsContextValue {
  downloads: Record<string, DownloadState>;
  currentModelId: string | null;
  currentBackend: string | null;
  startDownload: (modelId: string, backend: "mlx" | "hf") => void;
  cancelDownload: (modelId: string) => void;
  refreshCurrent: () => Promise<void>;
  subscribe: (listener: (event: DownloadEvent) => void) => () => void;
  /** Is any download currently in-flight? (Backend is single-slot.) */
  isAnyActive: boolean;
}

const DownloadsContext = createContext<DownloadsContextValue | null>(null);

export function DownloadsProvider({ children }: { children: ReactNode }) {
  const [downloads, setDownloads] = useState<Record<string, DownloadState>>({});
  const [currentModelId, setCurrentModelId] = useState<string | null>(null);
  const [currentBackend, setCurrentBackend] = useState<string | null>(null);

  const socketsRef = useRef<Map<string, WebSocket>>(new Map());
  const listenersRef = useRef<Set<(e: DownloadEvent) => void>>(new Set());

  const notify = useCallback((event: DownloadEvent) => {
    listenersRef.current.forEach((l) => {
      try { l(event); } catch { /* listener errors are non-fatal */ }
    });
  }, []);

  const refreshCurrent = useCallback(async () => {
    try {
      const data = await modelsApi.current();
      if (data.loaded && data.model_id) {
        setCurrentModelId(data.model_id);
        setCurrentBackend(data.backend ?? null);
      } else {
        setCurrentModelId(null);
        setCurrentBackend(null);
      }
    } catch {
      // silently fail — UI will just show stale state
    }
  }, []);

  // Pull current model on mount
  useEffect(() => {
    refreshCurrent();
  }, [refreshCurrent]);

  const cancelDownload = useCallback((modelId: string) => {
    const ws = socketsRef.current.get(modelId);
    if (ws) {
      ws.close();
      socketsRef.current.delete(modelId);
    }
    setDownloads((prev) => {
      const { [modelId]: _dropped, ...rest } = prev;
      return rest;
    });
  }, []);

  const startDownload = useCallback(
    (modelId: string, backend: "mlx" | "hf") => {
      // If there's already a socket for this model, don't start another.
      if (socketsRef.current.has(modelId)) return;

      setDownloads((prev) => ({
        ...prev,
        [modelId]: {
          modelId,
          backend,
          status: "downloading",
          progress: 0,
          message: "Connecting...",
          startedAt: Date.now(),
        },
      }));

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/models/load`);
      socketsRef.current.set(modelId, ws);

      ws.onopen = () => {
        ws.send(JSON.stringify({ model_id: modelId, backend }));
      };

      ws.onmessage = (event) => {
        let msg: any;
        try { msg = JSON.parse(event.data); } catch { return; }

        if (msg.type === "progress") {
          setDownloads((prev) => ({
            ...prev,
            [modelId]: {
              ...(prev[modelId] ?? { modelId, backend, startedAt: Date.now() }),
              modelId,
              backend,
              status: msg.progress > 0.9 ? "loading" : "downloading",
              progress: msg.progress,
              message: msg.message ?? "",
            } as DownloadState,
          }));
        } else if (msg.type === "done") {
          socketsRef.current.delete(modelId);
          setCurrentModelId(msg.model_id ?? modelId);
          setCurrentBackend(msg.backend ?? backend);
          setDownloads((prev) => {
            const { [modelId]: _dropped, ...rest } = prev;
            return rest;
          });
          notify({ type: "completed", modelId: msg.model_id ?? modelId, backend: msg.backend ?? backend });
          ws.close();
        } else if (msg.type === "error") {
          socketsRef.current.delete(modelId);
          setDownloads((prev) => ({
            ...prev,
            [modelId]: {
              ...(prev[modelId] ?? { modelId, backend, progress: 0, message: "", startedAt: Date.now() }),
              status: "error",
              error: msg.message ?? "Unknown error",
              message: msg.message ?? "Failed",
            } as DownloadState,
          }));
          notify({ type: "failed", modelId, error: msg.message ?? "Unknown error" });
          ws.close();
        }
      };

      ws.onclose = () => {
        // If we get here without a done/error, treat it as a drop.
        socketsRef.current.delete(modelId);
        setDownloads((prev) => {
          const cur = prev[modelId];
          if (!cur || cur.status === "error") return prev;
          // If socket closed before completion, mark error
          if (cur.status !== "ready") {
            return {
              ...prev,
              [modelId]: { ...cur, status: "error", error: "Connection lost", message: "Connection lost" },
            };
          }
          return prev;
        });
      };

      ws.onerror = () => {
        // Treat onerror as terminal; cleanup happens in onclose.
      };
    },
    [notify]
  );

  const subscribe = useCallback((listener: (e: DownloadEvent) => void) => {
    listenersRef.current.add(listener);
    return () => { listenersRef.current.delete(listener); };
  }, []);

  const isAnyActive = Object.values(downloads).some(
    (d) => d.status === "downloading" || d.status === "loading"
  );

  const value: DownloadsContextValue = {
    downloads,
    currentModelId,
    currentBackend,
    startDownload,
    cancelDownload,
    refreshCurrent,
    subscribe,
    isAnyActive,
  };

  return <DownloadsContext.Provider value={value}>{children}</DownloadsContext.Provider>;
}

export function useDownloads(): DownloadsContextValue {
  const ctx = useContext(DownloadsContext);
  if (!ctx) {
    throw new Error("useDownloads must be used within <DownloadsProvider>");
  }
  return ctx;
}
