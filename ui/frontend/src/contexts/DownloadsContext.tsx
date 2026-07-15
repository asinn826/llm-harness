/**
 * DownloadsContext — app-wide state for in-flight model loads.
 *
 * Why this exists: model downloads need to survive navigation
 * (Chat ↔ Models) so both the Models page cards AND the sidebar
 * ModelSwitcher can reflect the same live progress. Local component
 * state loses this on unmount.
 *
 * Owns:
 * - `downloads`: Record keyed by model/backend/revision → DownloadState
 * - `currentModelId` / `currentBackend`: the one loaded model (singleton)
 * - A Map<model/backend/revision, WebSocket> for active sockets
 *
 * Exposes:
 * - startDownload(modelId, backend) — opens WS to /ws/models/load
 * - cancelDownload(modelId, backend, revision) — closes the WS. Server-side
 *   work cannot be cancelled, so the transfer remains visibly blocked.
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
import { models as modelsApi, wsUrl } from "../lib/api";
import { getTransferKey } from "../lib/transfers";

export type DownloadEvent =
  | { type: "completed"; modelId: string; backend: "mlx" | "hf"; revision: string | null }
  | { type: "failed"; modelId: string; revision: string | null; error: string };

interface DownloadsContextValue {
  downloads: Record<string, DownloadState>;
  currentModelId: string | null;
  currentBackend: string | null;
  currentRevision: string | null;
  startDownload: (modelId: string, backend: "mlx" | "hf", revision?: string | null) => void;
  startInstall: (modelId: string, backend: "mlx" | "hf", revision: string) => void;
  cancelDownload: (
    modelId: string,
    backend: "mlx" | "hf",
    revision?: string | null,
  ) => void;
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
  const [currentRevision, setCurrentRevision] = useState<string | null>(null);

  const socketsRef = useRef<Map<string, WebSocket>>(new Map());
  const stoppedTransfersRef = useRef<Set<string>>(new Set());
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
        setCurrentRevision(data.revision ?? null);
      } else {
        setCurrentModelId(null);
        setCurrentBackend(null);
        setCurrentRevision(null);
      }
    } catch {
      // silently fail — UI will just show stale state
    }
  }, []);

  // Pull current model on mount
  useEffect(() => {
    const timer = window.setTimeout(() => { void refreshCurrent(); }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshCurrent]);

  const cancelDownload = useCallback((
    modelId: string,
    backend: "mlx" | "hf",
    revision: string | null = null,
  ) => {
    const transferKey = getTransferKey(modelId, backend, revision);
    const ws = socketsRef.current.get(transferKey);
    stoppedTransfersRef.current.add(transferKey);
    if (ws && socketsRef.current.get(transferKey) === ws) {
      socketsRef.current.delete(transferKey);
    }
    setDownloads((prev) => {
      const current = prev[transferKey];
      if (!current) return prev;
      return {
        ...prev,
        [transferKey]: {
          ...current,
          status: "error",
          message: "Stopped watching",
          error: "Stopped watching. The model operation may still be running in the background.",
        },
      };
    });
    ws?.close();
  }, []);

  const startTransfer = useCallback(
    (
      modelId: string,
      backend: "mlx" | "hf",
      revision: string | null,
      operation: "install" | "load",
    ) => {
      const transferKey = getTransferKey(modelId, backend, revision);
      // Do not duplicate this exact model/backend/revision operation.
      if (socketsRef.current.has(transferKey)) return;
      stoppedTransfersRef.current.delete(transferKey);

      setDownloads((prev) => ({
        ...prev,
        [transferKey]: {
          modelId,
          backend,
          revision,
          operation,
          status: "downloading",
          progress: 0,
          message: "Connecting...",
          startedAt: Date.now(),
        },
      }));

      const ws = new WebSocket(wsUrl(
        operation === "install" ? "/ws/models/install" : "/ws/models/load"
      ));
      socketsRef.current.set(transferKey, ws);

      ws.onopen = () => {
        ws.send(JSON.stringify({ model_id: modelId, backend, revision }));
      };

      ws.onmessage = (event) => {
        if (
          stoppedTransfersRef.current.has(transferKey) ||
          socketsRef.current.get(transferKey) !== ws
        ) return;

        let msg: {
          type?: string;
          progress?: number;
          message?: string;
          model_id?: string;
          backend?: "mlx" | "hf";
          revision?: string | null;
        };
        try { msg = JSON.parse(event.data) as typeof msg; } catch { return; }

        if (msg.type === "progress") {
          setDownloads((prev) => ({
            ...prev,
            [transferKey]: {
              ...(prev[transferKey] ?? { modelId, backend, revision, operation, startedAt: Date.now() }),
              modelId,
              backend,
              revision,
              operation,
              status: (msg.progress ?? 0) > 0.9 ? "loading" : "downloading",
              progress: msg.progress ?? 0,
              message: msg.message ?? "",
            } as DownloadState,
          }));
        } else if (msg.type === "done") {
          if (socketsRef.current.get(transferKey) === ws) {
            socketsRef.current.delete(transferKey);
          }
          if (operation === "load") {
            setCurrentModelId(msg.model_id ?? modelId);
            setCurrentBackend(msg.backend ?? backend);
            setCurrentRevision(msg.revision ?? revision);
          }
          setDownloads((prev) => {
            const existing = prev[transferKey];
            return {
              ...prev,
              [transferKey]: {
                ...(existing ?? { modelId, backend, revision, operation, startedAt: Date.now() }),
                modelId,
                backend: msg.backend ?? backend,
                revision: msg.revision ?? revision,
                operation,
                status: "ready",
                progress: 1,
                message: operation === "install" ? "Installed" : "Ready",
              },
            };
          });
          notify({
            type: "completed",
            modelId: msg.model_id ?? modelId,
            backend: msg.backend ?? backend,
            revision: msg.revision ?? revision,
          });
          ws.close();
        } else if (msg.type === "error") {
          if (socketsRef.current.get(transferKey) === ws) {
            socketsRef.current.delete(transferKey);
          }
          setDownloads((prev) => ({
            ...prev,
            [transferKey]: {
              ...(prev[transferKey] ?? { modelId, backend, revision, operation, progress: 0, message: "", startedAt: Date.now() }),
              status: "error",
              error: msg.message ?? "Unknown error",
              message: msg.message ?? "Failed",
            } as DownloadState,
          }));
          notify({ type: "failed", modelId, revision, error: msg.message ?? "Unknown error" });
          ws.close();
        }
      };

      ws.onclose = () => {
        if (stoppedTransfersRef.current.has(transferKey)) return;
        if (socketsRef.current.get(transferKey) !== ws) return;
        // If we get here without a done/error, treat it as a drop.
        socketsRef.current.delete(transferKey);
        setDownloads((prev) => {
          const cur = prev[transferKey];
          if (!cur || cur.status === "error") return prev;
          // If socket closed before completion, mark error
          if (cur.status !== "ready") {
            return {
              ...prev,
              [transferKey]: { ...cur, status: "error", error: "Connection lost", message: "Connection lost" },
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

  const startDownload = useCallback(
    (modelId: string, backend: "mlx" | "hf", revision: string | null = null) => {
      startTransfer(modelId, backend, revision, "load");
    },
    [startTransfer]
  );

  const startInstall = useCallback(
    (modelId: string, backend: "mlx" | "hf", revision: string) => {
      startTransfer(modelId, backend, revision, "install");
    },
    [startTransfer]
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
    currentRevision,
    startDownload,
    startInstall,
    cancelDownload,
    refreshCurrent,
    subscribe,
    isAnyActive,
  };

  return <DownloadsContext.Provider value={value}>{children}</DownloadsContext.Provider>;
}

// Hook and provider intentionally share this module.
// eslint-disable-next-line react-refresh/only-export-components
export function useDownloads(): DownloadsContextValue {
  const ctx = useContext(DownloadsContext);
  if (!ctx) {
    throw new Error("useDownloads must be used within <DownloadsProvider>");
  }
  return ctx;
}
