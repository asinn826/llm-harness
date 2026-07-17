/**
 * ModelDetailsDrawer — right-side slide-in panel with full model info.
 *
 * Two tabs: Overview (metadata grid + tags) and Model card (README).
 * Action row mirrors the ModelCard's actions.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  X,
  ExternalLink,
  Download,
  Check,
  Loader2,
  Lock,
  AlertTriangle,
  RefreshCw,
  Plus,
} from "lucide-react";
import { models as modelsApi } from "../lib/api";
import type { ComparisonModelInput, ModelDetails, ModelPreflight } from "../lib/types";
import { getModelColor } from "../lib/types";
import { useDownloads } from "../contexts/DownloadsContext";
import { getTransferKey } from "../lib/transfers";

interface ModelDetailsDrawerProps {
  modelId: string | null;
  backend: "mlx" | "hf";
  isCached: boolean;
  gated?: boolean;
  selectionMode?: boolean;
  isSelected?: boolean;
  selectionFull?: boolean;
  onAddToComparison?: (model: ComparisonModelInput) => void;
  onRemoveFromComparison?: (modelId: string) => void;
  onClose: () => void;
}

type InnerTab = "overview" | "card";

export function ModelDetailsDrawer({
  modelId,
  backend,
  isCached,
  gated = false,
  selectionMode = false,
  isSelected = false,
  selectionFull = false,
  onAddToComparison,
  onRemoveFromComparison,
  onClose,
}: ModelDetailsDrawerProps) {
  const {
    downloads,
    currentModelId,
    currentBackend,
    currentRevision,
    startDownload,
    startInstall,
    cancelDownload,
  } = useDownloads();
  const [tab, setTab] = useState<InnerTab>("overview");
  const [details, setDetails] = useState<ModelDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revisionInput, setRevisionInput] = useState("main");
  const [preflight, setPreflight] = useState<ModelPreflight | null>(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);

  // Per-session cache so re-opening is instant
  const cacheRef = useRef<Map<string, ModelDetails>>(new Map());
  const preflightRequestRef = useRef(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);

  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!modelId) return;
    const cached = cacheRef.current.get(modelId);
    if (cached) {
      setDetails(cached);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    modelsApi.details(modelId)
      .then((d) => {
        cacheRef.current.set(modelId, d);
        setDetails(d);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [modelId]);

  const runPreflight = useCallback(async () => {
    if (!modelId) return;
    const requestId = ++preflightRequestRef.current;
    const requestedRevision = revisionInput.trim() || null;
    setPreflightLoading(true);
    setPreflightError(null);
    try {
      const result = await modelsApi.preflight({
        model_id: modelId,
        backend,
        revision: requestedRevision,
      });
      if (preflightRequestRef.current !== requestId) return;
      setPreflight(result);
    } catch (e) {
      if (preflightRequestRef.current !== requestId) return;
      setPreflight(null);
      setPreflightError(e instanceof Error ? e.message : String(e));
    } finally {
      if (preflightRequestRef.current === requestId) {
        setPreflightLoading(false);
      }
    }
  }, [backend, modelId, revisionInput]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void runPreflight(); }, 0);
    return () => {
      window.clearTimeout(timer);
      preflightRequestRef.current += 1;
    };
  }, [runPreflight]);

  // Keep keyboard focus inside the modal drawer and restore it on close.
  useEffect(() => {
    if (!modelId) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const frame = window.requestAnimationFrame(() => dialogRef.current?.focus());
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )).filter((element) => element.getClientRects().length > 0);
      if (focusable.length === 0) {
        e.preventDefault();
        dialogRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && (document.activeElement === first || !dialogRef.current.contains(document.activeElement))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", handler);
      previousFocus?.focus();
    };
  }, [modelId]);

  if (!modelId) return null;

  const requestedRevision = revisionInput.trim() || null;
  const activePreflight = preflight &&
    preflight.model_id === modelId &&
    preflight.backend === backend &&
    (preflight.requested_revision ?? null) === requestedRevision
      ? preflight
      : null;
  const transferBackend = activePreflight?.backend ?? backend;
  const transferRevision = activePreflight?.resolved_revision ?? null;
  const transferKey = getTransferKey(modelId, transferBackend, transferRevision);
  const dl = downloads[transferKey];
  const isActive = currentModelId === modelId;
  const isPinnedActive = isActive &&
    currentBackend === transferBackend &&
    (!activePreflight?.resolved_revision || currentRevision === activePreflight.resolved_revision);
  const isBusy = dl?.status === "downloading" || dl?.status === "loading";
  const isReady = dl?.status === "ready";
  const needsTransferRetry = dl?.status === "error";
  const visiblePreflight = activePreflight && isReady
    ? { ...activePreflight, cache_status: "complete" as const }
    : activePreflight;
  const color = getModelColor(modelId);
  const exactRevisionCached = activePreflight?.cache_status === "complete" || (
    activePreflight?.cache_status === undefined && isCached
  );
  const canUse = Boolean(activePreflight?.can_load && activePreflight.resolved_revision);

  const selectedModel: ComparisonModelInput | null = activePreflight?.resolved_revision
    ? {
        model_id: modelId,
        backend: activePreflight.backend,
        revision: activePreflight.resolved_revision,
      }
    : null;

  const handleInstallOrAdd = () => {
    if (!selectedModel || !activePreflight?.can_load || !activePreflight.resolved_revision) return;
    const resolvedRevision = activePreflight.resolved_revision;
    onAddToComparison?.(selectedModel);
    if ((!exactRevisionCached || needsTransferRetry) && !isReady && !isPinnedActive && !isBusy) {
      startInstall(modelId, activePreflight.backend, resolvedRevision);
    }
  };

  const handleLoad = () => {
    if (!activePreflight?.can_load || !activePreflight.resolved_revision) return;
    startDownload(modelId, activePreflight.backend, activePreflight.resolved_revision);
  };

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0, 0, 0, 0.4)",
          zIndex: 90,
        }}
      />
      {/* Drawer */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Details for ${modelId}`}
        tabIndex={-1}
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          width: 440,
          background: "var(--bg-primary)",
          borderLeft: "1px solid var(--border-default)",
          display: "flex",
          flexDirection: "column",
          zIndex: 100,
          boxShadow: "-8px 0 24px rgba(0, 0, 0, 0.3)",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--border-subtle)",
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexShrink: 0,
          }}
        >
          <div style={{ width: 10, height: 10, borderRadius: "50%", background: color, flexShrink: 0 }} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {modelId.split("/").pop()}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {modelId.split("/")[0]}
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close model details"
            style={{
              width: 28, height: 28,
              display: "flex", alignItems: "center", justifyContent: "center",
              background: "transparent", border: "none",
              color: "var(--text-muted)", cursor: "pointer",
              borderRadius: 4,
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Action row */}
        <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--border-subtle)", flexShrink: 0, display: "flex", alignItems: "center", gap: 10 }}>
          {selectionMode && isSelected && (
            <button
              onClick={() => onRemoveFromComparison?.(modelId)}
              style={{ ...primaryBtn, background: "var(--success-muted)", color: "var(--success)" }}
            >
              <Check size={12} style={{ marginRight: 6 }} /> Selected
            </button>
          )}
          {selectionMode && isSelected && needsTransferRetry && canUse && (
            <button
              onClick={() => startInstall(modelId, transferBackend, transferRevision!)}
              style={{ ...primaryBtn, background: "var(--error-muted)", color: "var(--error)" }}
            >
              <RefreshCw size={12} style={{ marginRight: 6 }} /> Retry install
            </button>
          )}
          {selectionMode && !isSelected && preflightLoading && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--text-muted)", fontSize: 12 }}>
              <Loader2 size={13} className="animate-spin" /> Checking…
            </span>
          )}
          {selectionMode && !isSelected && !preflightLoading && canUse && !isBusy && (
            <button
              onClick={handleInstallOrAdd}
              disabled={selectionFull}
              style={{ ...primaryBtn, opacity: selectionFull ? 0.45 : 1, cursor: selectionFull ? "not-allowed" : "pointer" }}
              title={selectionFull ? "Three models selected" : undefined}
            >
              {exactRevisionCached && !needsTransferRetry || isReady ? <Plus size={12} style={{ marginRight: 6 }} /> : <Download size={12} style={{ marginRight: 6 }} />}
              {selectionFull
                ? "3 selected"
                : needsTransferRetry
                  ? "Retry install & add"
                  : exactRevisionCached || isReady
                  ? "Add to comparison"
                  : "Install & add"}
            </button>
          )}
          {selectionMode && !isSelected && !preflightLoading && !canUse && activePreflight?.access === "token_required" && (
            <a
              href={`https://huggingface.co/${modelId}`}
              target="_blank"
              rel="noreferrer"
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "6px 12px",
                background: "var(--warning-muted)", color: "var(--warning)",
                border: "1px solid rgba(229, 168, 32, 0.3)",
                borderRadius: 6,
                fontSize: 12, fontWeight: 500,
                textDecoration: "none",
              }}
            >
              <Lock size={12} /> Get model access
            </a>
          )}
          {!selectionMode && !isPinnedActive && !isBusy && canUse && (
            <button
              onClick={handleLoad}
              style={primaryBtn}
            >
              <Download size={12} style={{ marginRight: 6 }} />
              {exactRevisionCached ? "Load model" : "Download & load"}
            </button>
          )}
          {!selectionMode && isPinnedActive && (
            <span
              style={{
                display: "inline-flex", alignItems: "center", gap: 4,
                fontSize: 12, padding: "6px 12px", borderRadius: 6,
                background: "var(--success-muted)", color: "var(--success)",
                fontWeight: 500,
              }}
            >
              <Check size={12} /> Active
            </span>
          )}
          {isBusy && dl && (
            <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 10 }}>
              <Loader2 size={14} className="animate-spin" style={{ color: "var(--accent)", flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {dl.message || "Loading..."}
                </div>
                <div style={{ height: 3, borderRadius: 2, background: "var(--bg-primary)", overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${Math.max(dl.progress * 100, 2)}%`, background: "var(--accent)", transition: "width 300ms ease-out" }} />
                </div>
              </div>
              <button
                onClick={() => cancelDownload(modelId, transferBackend, transferRevision)}
                style={iconBtn}
                title="Stop watching"
                aria-label={`Stop watching ${modelId}`}
              >
                <X size={14} />
              </button>
            </div>
          )}
          <div style={{ flex: 1 }} />
          <a
            href={`https://huggingface.co/${modelId}`}
            target="_blank"
            rel="noreferrer"
            style={{
              color: "var(--text-muted)", textDecoration: "none",
              display: "inline-flex", alignItems: "center", gap: 4,
              fontSize: 12,
            }}
            title="View on HuggingFace"
          >
            <ExternalLink size={12} />
          </a>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", padding: "0 20px", borderBottom: "1px solid var(--border-subtle)", flexShrink: 0, gap: 16 }}>
          <InnerTabButton label="Overview" active={tab === "overview"} onClick={() => setTab("overview")} />
          <InnerTabButton label="Model card" active={tab === "card"} onClick={() => setTab("card")} />
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {tab === "overview" && (
            <PreflightPanel
              modelId={modelId}
              revision={revisionInput}
              onRevisionChange={setRevisionInput}
              onCheck={runPreflight}
              loading={preflightLoading}
              error={preflightError}
              result={visiblePreflight}
              fallbackGated={gated}
            />
          )}
          {loading && <LoadingState />}
          {error && <ErrorState message={error} />}
          {details && !loading && !error && tab === "overview" && (
            <OverviewTab details={details} modelId={modelId} />
          )}
          {details && !loading && !error && tab === "card" && (
            <CardTab readme={details.readme_markdown} />
          )}
        </div>
      </div>
    </>
  );
}

// ── Tab contents ──────────────────────────────────────────────────────

function PreflightPanel({
  modelId,
  revision,
  onRevisionChange,
  onCheck,
  loading,
  error,
  result,
  fallbackGated,
}: {
  modelId: string;
  revision: string;
  onRevisionChange: (value: string) => void;
  onCheck: () => void;
  loading: boolean;
  error: string | null;
  result: ModelPreflight | null;
  fallbackGated: boolean;
}) {
  const statusColor = result?.can_load
    ? "var(--success)"
    : result?.error || error
      ? "var(--error)"
      : "var(--text-muted)";

  const rows: [string, string][] = result ? [
    ["Access", result.access === "authorized" ? "Gated · authorized" : result.access.replace("_", " ")],
    ["Runtime", result.runtime_available === false ? `${result.backend.toUpperCase()} unavailable` : result.backend.toUpperCase()],
    ["Weights", formatBytes(result.model_size_bytes)],
    ["Memory", `${formatBytes(result.estimated_memory_bytes)} · ${result.memory_fit.replace("_", " ")}`],
    ["Disk", result.cache_status === "complete"
      ? "Already installed"
      : `${formatBytes(result.required_download_bytes ?? result.model_size_bytes)} · ${(result.disk_fit ?? "unknown").replace("_", " ")}`],
    ["Local cache", result.cache_status ?? "unknown"],
    ["Pinned commit", result.resolved_revision ? result.resolved_revision.slice(0, 12) : "unresolved"],
  ] : [];

  return (
    <div style={{ padding: "16px 20px 0" }}>
      <div style={{
        border: "1px solid var(--border-default)", borderRadius: 8,
        background: "var(--bg-secondary)", overflow: "hidden",
      }}>
        <div style={{ padding: 12, borderBottom: "1px solid var(--border-subtle)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}>
            <span style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)" }}>Revision</span>
            <span style={{ flex: 1 }} />
            {loading && <Loader2 size={12} className="animate-spin" style={{ color: "var(--accent)" }} />}
            {!loading && result && (
              <span style={{ fontSize: 12, color: statusColor, fontWeight: 500 }}>
                {result.can_load ? "Ready" : "Unavailable"}
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <input
              aria-label="Hugging Face revision"
              value={revision}
              onChange={(event) => onRevisionChange(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") onCheck(); }}
              placeholder="main, tag, or commit"
              style={{
                flex: 1, minWidth: 0, padding: "6px 8px", borderRadius: 5,
                border: "1px solid var(--border-default)", background: "var(--bg-primary)",
                color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontSize: 12,
              }}
            />
            <button onClick={onCheck} disabled={loading} style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              padding: "6px 9px", borderRadius: 5,
              border: "1px solid var(--border-default)", background: "var(--bg-tertiary)",
              color: "var(--text-secondary)", fontSize: 14, cursor: loading ? "wait" : "pointer",
            }}>
              <RefreshCw size={11} /> Check
            </button>
          </div>
        </div>

        {loading && !result && (
          <div style={{ padding: 12, fontSize: 12, color: "var(--text-muted)" }}>
            Checking {modelId}…
          </div>
        )}

        {error && (
          <div style={{ display: "flex", gap: 7, padding: 12, color: "var(--error)", fontSize: 12, lineHeight: 1.45 }}>
            <AlertTriangle size={13} style={{ flexShrink: 0, marginTop: 1 }} /> {error}
          </div>
        )}

        {!result && !loading && !error && fallbackGated && (
          <div style={{ padding: 12, color: "var(--warning)", fontSize: 12 }}>
            This model may require accepted terms and a Hugging Face token.
          </div>
        )}

        {result && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 16px", padding: 12 }}>
              {rows.map(([label, value]) => (
                <div key={label}>
                  <div style={{ color: "var(--text-muted)", fontSize: 12, marginBottom: 2 }}>{label}</div>
                  <div style={{ color: "var(--text-primary)", fontSize: 14, textTransform: label === "Local cache" ? "capitalize" : undefined }}>{value}</div>
                </div>
              ))}
            </div>
            {result.error && (
              <div style={{
                display: "flex", gap: 7, padding: "10px 12px",
                borderTop: "1px solid var(--border-subtle)",
                background: "var(--error-muted)", color: "var(--error)", fontSize: 12, lineHeight: 1.45,
              }}>
                <AlertTriangle size={13} style={{ flexShrink: 0, marginTop: 1 }} />
                <span>{result.error.message}</span>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function OverviewTab({ details, modelId }: { details: ModelDetails; modelId: string }) {
  const metaRows: [string, React.ReactNode][] = [
    ["Author", modelId.split("/")[0]],
    ["License", details.license || "—"],
    ["Pipeline", details.pipeline_tag || "—"],
    ["Size", details.model_size_bytes > 0 ? formatBytes(details.model_size_bytes) : "—"],
    ["Downloads", formatCount(details.downloads)],
    ["Likes", formatCount(details.likes)],
    ["Last modified", details.last_modified ? formatDate(details.last_modified) : "—"],
  ];

  return (
    <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Metadata grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px 20px" }}>
        {metaRows.map(([label, value]) => (
          <div key={label}>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 3 }}>
              {label}
            </div>
            <div style={{ fontSize: 14, color: "var(--text-primary)" }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Tags */}
      {details.tags.length > 0 && (
        <div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>
            Tags
          </div>
          <div style={{ fontSize: 14, color: "var(--text-tertiary)", lineHeight: 1.5 }}>
            {details.tags.slice(0, 20).join(", ")}
          </div>
        </div>
      )}
    </div>
  );
}

function CardTab({ readme }: { readme: string }) {
  if (!readme.trim()) {
    return (
      <div style={{ padding: 20, fontSize: 14, color: "var(--text-muted)" }}>
        No model card available.
      </div>
    );
  }
  return (
    <div style={{
      padding: 20,
      fontSize: 14,
      lineHeight: 1.6,
      color: "var(--text-secondary)",
    }}>
      <div className="drawer-readme">
        <ReactMarkdown>{readme}</ReactMarkdown>
      </div>
    </div>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────────

function LoadingState() {
  const widths = [78, 64, 86, 72];
  return (
    <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 12 }}>
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            height: 14,
            width: `${widths[i]}%`,
            borderRadius: 3,
            background: "var(--bg-elevated)",
            opacity: 0.5,
          }}
        />
      ))}
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div style={{ padding: 20, fontSize: 12, color: "var(--error)" }}>
      {message}
    </div>
  );
}

function InnerTabButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "10px 2px",
        background: "none",
        border: "none",
        borderBottom: `2px solid ${active ? "var(--accent)" : "transparent"}`,
        color: active ? "var(--text-primary)" : "var(--text-tertiary)",
        fontSize: 12,
        fontWeight: active ? 500 : 400,
        cursor: "pointer",
        transition: "color 120ms ease-out, border-color 120ms ease-out",
      }}
    >
      {label}
    </button>
  );
}

function formatBytes(n: number): string {
  if (n <= 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(1)} ${units[i]}`;
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000);
    if (diffDays < 1) return "today";
    if (diffDays < 7) return `${diffDays}d ago`;
    if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

const primaryBtn: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "6px 14px",
  background: "var(--accent)",
  color: "white",
  border: "none",
  borderRadius: 6,
  fontSize: 12,
  fontWeight: 500,
  cursor: "pointer",
};

const iconBtn: React.CSSProperties = {
  width: 24, height: 24,
  display: "inline-flex", alignItems: "center", justifyContent: "center",
  background: "transparent", border: "none",
  color: "var(--text-muted)", cursor: "pointer",
  borderRadius: 4,
};
