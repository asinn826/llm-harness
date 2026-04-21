/**
 * ModelDetailsDrawer — right-side slide-in panel with full model info.
 *
 * Two tabs: Overview (metadata grid + tags) and Model card (README).
 * Action row mirrors the ModelCard's actions.
 */

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  X,
  ExternalLink,
  Download,
  Check,
  Loader2,
  Lock,
  HardDrive,
  Heart,
  TrendingUp,
  Calendar,
} from "lucide-react";
import { models as modelsApi } from "../lib/api";
import type { ModelDetails } from "../lib/types";
import { getModelColor } from "../lib/types";
import { useDownloads } from "../contexts/DownloadsContext";

interface ModelDetailsDrawerProps {
  modelId: string | null;
  backend: "mlx" | "hf";
  isCached: boolean;
  gated?: boolean;
  onClose: () => void;
}

type InnerTab = "overview" | "card";

export function ModelDetailsDrawer({
  modelId,
  backend,
  isCached,
  gated = false,
  onClose,
}: ModelDetailsDrawerProps) {
  const { downloads, currentModelId, startDownload, cancelDownload } = useDownloads();
  const [tab, setTab] = useState<InnerTab>("overview");
  const [details, setDetails] = useState<ModelDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Per-session cache so re-opening is instant
  const cacheRef = useRef<Map<string, ModelDetails>>(new Map());

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

  // Close on Esc
  useEffect(() => {
    if (!modelId) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [modelId, onClose]);

  if (!modelId) return null;

  const dl = downloads[modelId];
  const isActive = currentModelId === modelId;
  const isBusy = dl?.status === "downloading" || dl?.status === "loading";
  const color = getModelColor(modelId);

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
        role="dialog"
        aria-label={`Details for ${modelId}`}
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
            <div style={{ fontSize: 11, color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {modelId.split("/")[0]}
            </div>
          </div>
          <button
            onClick={onClose}
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
          {gated && !isCached && !isActive && (
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
              <Lock size={12} /> Open on HuggingFace
            </a>
          )}
          {!gated && !isCached && !isActive && !isBusy && (
            <button
              onClick={() => startDownload(modelId, backend)}
              style={primaryBtn}
            >
              <Download size={12} style={{ marginRight: 6 }} /> Download
            </button>
          )}
          {isCached && !isActive && !isBusy && (
            <button onClick={() => startDownload(modelId, backend)} style={primaryBtn}>
              Load model
            </button>
          )}
          {isActive && (
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
                <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {dl.message || "Loading..."}
                </div>
                <div style={{ height: 3, borderRadius: 2, background: "var(--bg-primary)", overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${Math.max(dl.progress * 100, 2)}%`, background: "var(--accent)", transition: "width 300ms ease-out" }} />
                </div>
              </div>
              <button onClick={() => cancelDownload(modelId)} style={iconBtn} title="Cancel">
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
              fontSize: 11,
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
            <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 3 }}>
              {label}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-primary)" }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Tags */}
      {details.tags.length > 0 && (
        <div>
          <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
            Tags
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {details.tags.slice(0, 20).map((t) => (
              <span key={t} style={{ fontSize: 10, padding: "2px 7px", borderRadius: 3, background: "var(--bg-elevated)", color: "var(--text-tertiary)" }}>
                {t}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CardTab({ readme }: { readme: string }) {
  if (!readme.trim()) {
    return (
      <div style={{ padding: 20, fontSize: 12, color: "var(--text-muted)" }}>
        No model card available.
      </div>
    );
  }
  return (
    <div style={{
      padding: 20,
      fontSize: 12,
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
  return (
    <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 12 }}>
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            height: 14,
            width: `${60 + Math.random() * 30}%`,
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
