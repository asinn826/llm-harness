/**
 * ModelCard — rich card for the Models page Library tab.
 *
 * One component, two variants:
 *   - "rich"    — full card with description, metadata chips, actions
 *   - "compact" — single-row for dense lists (reserved for PR 3)
 *
 * Action button states derived from DownloadsContext:
 *   - Not cached, no in-flight → [Download]  (accent button)
 *   - Cached, not loaded       → [Load model] (secondary)
 *   - Downloading / loading    → inline progress bar + status text + cancel
 *   - Loaded (current)         → [Active ✓]   (success)
 *   - Error                    → [Retry]     (+ red error text)
 */

import { useState } from "react";
import {
  Download,
  Check,
  X as XIcon,
  ExternalLink,
  Flame,
  Snowflake,
  Thermometer,
  ShieldCheck,
  HelpCircle,
  Star,
  MoreHorizontal,
  Trash2,
  Copy,
} from "lucide-react";
import type { ModelInfo } from "../lib/types";
import { getModelColor } from "../lib/types";
import { useDownloads } from "../contexts/DownloadsContext";
import { HardwareFitChip } from "./HardwareFitChip";
import { UpdateBadge } from "./UpdateBadge";
import { ConfirmDialog } from "./ConfirmDialog";
import { models as modelsApi } from "../lib/api";

interface ModelCardProps {
  model: ModelInfo;
  variant?: "rich" | "compact";
  /** If true, a small "Recommended" star badge renders in the header row. */
  starred?: boolean;
  /** Whether this model has a newer Hub commit — shows UpdateBadge. */
  hasUpdate?: boolean;
  /** Called after a successful cache deletion (parent refetches list). */
  onDeleted?: () => void;
}

export function ModelCard({ model, variant = "rich", starred = false, hasUpdate = false, onDeleted }: ModelCardProps) {
  const { downloads, currentModelId, startDownload, cancelDownload } = useDownloads();
  const [menuOpen, setMenuOpen] = useState(false);
  const [deleteDialog, setDeleteDialog] = useState(false);
  const [unloadDialog, setUnloadDialog] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const dl = downloads[model.id];
  const isActive = currentModelId === model.id;
  const isBusy = dl?.status === "downloading" || dl?.status === "loading";
  const isError = dl?.status === "error";
  const hasSuperseded = (model.supersedes_cached?.length ?? 0) > 0;

  const color = getModelColor(model.id);

  const handleDelete = async () => {
    setDeleteError(null);
    try {
      await modelsApi.deleteCache(model.id);
      setDeleteDialog(false);
      onDeleted?.();
    } catch (e: any) {
      // 409 when currently loaded
      const msg = String(e?.message ?? e);
      if (msg.toLowerCase().includes("loaded") || msg.toLowerCase().includes("unload")) {
        setDeleteDialog(false);
        setUnloadDialog(true);
      } else {
        setDeleteError(msg);
      }
    }
  };

  const handleCopyId = () => {
    navigator.clipboard?.writeText(model.id).catch(() => {});
    setMenuOpen(false);
  };

  if (variant === "compact") {
    return renderCompact({
      model, color, isActive, isBusy, isError, dl,
      startDownload, cancelDownload,
    });
  }

  // ── RICH variant ─────────────────────────────────────────────────

  return (
    <div
      style={{
        border: "1px solid var(--border-subtle)",
        borderRadius: 10,
        padding: 16,
        background: "var(--bg-secondary)",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        minHeight: 160,
        transition: "background 120ms ease-out",
      }}
    >
      {/* Row 1: dot, name, badges */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <div
          style={{
            width: 10, height: 10, borderRadius: "50%",
            background: color, flexShrink: 0,
          }}
        />
        <span
          style={{
            fontSize: 14, fontWeight: 600, color: "var(--text-primary)",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}
        >
          {model.name}
        </span>
        {starred && (
          <span title="Recommended" style={{ color: "var(--warning)", display: "flex" }}>
            <Star size={12} fill="currentColor" />
          </span>
        )}
        <BackendBadge backend={model.backend} />
        <HeatIcon heat={model.heat} />
        <ToolUseBadge tier={model.tool_use_tier} />
        <HardwareFitChip model={model} />
        <div style={{ flex: 1 }} />
        {hasUpdate && !isActive && (
          <UpdateBadge kind="commit" title="A newer version of this model is available on HuggingFace" onClick={() => startDownload(model.id, model.backend)} />
        )}
        {hasSuperseded && !isActive && (
          <UpdateBadge
            kind="superseded"
            title={`A newer curated version is available. You have: ${(model.supersedes_cached || []).join(", ")}`}
          />
        )}
        {isActive && (
          <span
            style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              fontSize: 10, padding: "2px 7px", borderRadius: 10,
              background: "var(--success-muted)", color: "var(--success)",
              fontWeight: 500,
            }}
          >
            <Check size={10} /> Active
          </span>
        )}
        {model.is_cached && (
          <div style={{ position: "relative" }}>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setMenuOpen(!menuOpen);
              }}
              style={iconBtnStyle}
              title="More"
            >
              <MoreHorizontal size={14} />
            </button>
            {menuOpen && (
              <>
                <div
                  onClick={() => setMenuOpen(false)}
                  style={{ position: "fixed", inset: 0, zIndex: 60 }}
                />
                <div
                  style={{
                    position: "absolute",
                    top: "100%", right: 0,
                    marginTop: 4,
                    minWidth: 180,
                    background: "var(--bg-tertiary)",
                    border: "1px solid var(--border-default)",
                    borderRadius: 6,
                    overflow: "hidden",
                    zIndex: 70,
                    boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
                  }}
                >
                  <MenuItem icon={<Copy size={12} />} label="Copy model ID" onClick={handleCopyId} />
                  <MenuItem
                    icon={<Trash2 size={12} />}
                    label="Delete from cache"
                    destructive
                    onClick={() => { setMenuOpen(false); setDeleteDialog(true); }}
                  />
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Row 2: metadata chips */}
      <div style={{ fontSize: 11, color: "var(--text-tertiary)", display: "flex", gap: 6, flexWrap: "wrap" }}>
        {model.author && <span>{model.author}</span>}
        {model.parameters && <Sep text={model.parameters} />}
        {model.quantization && <Sep text={model.quantization} />}
        {(model.size_label || model.size) && <Sep text={model.size_label || model.size!} />}
        {model.context_window && <Sep text={`${(model.context_window / 1024).toFixed(0)}k ctx`} />}
      </div>

      {/* Row 3: description */}
      {model.description && (
        <p
          style={{
            fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.5,
            margin: 0,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {model.description}
        </p>
      )}

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Row 5: actions */}
      <ActionRow
        model={model}
        isActive={isActive}
        isBusy={isBusy}
        isError={isError}
        dl={dl}
        onStart={() => startDownload(model.id, model.backend)}
        onCancel={() => cancelDownload(model.id)}
      />

      {/* Delete confirmation */}
      {deleteDialog && (
        <ConfirmDialog
          title="Remove from cache?"
          body={
            <>
              <strong>{model.name}</strong>
              {model.size_label ? ` (${model.size_label})` : ""} will be deleted from{" "}
              <code style={{ fontFamily: "var(--font-mono)", fontSize: 11, padding: "1px 4px", background: "var(--bg-elevated)", borderRadius: 3 }}>
                ~/.cache/huggingface/hub
              </code>. You can re-download it later.
              {deleteError && (
                <div style={{ marginTop: 10, color: "var(--error)", fontSize: 11 }}>{deleteError}</div>
              )}
            </>
          }
          confirmLabel="Delete"
          destructive
          onConfirm={handleDelete}
          onCancel={() => { setDeleteDialog(false); setDeleteError(null); }}
        />
      )}

      {/* 409: model is loaded — offer to unload */}
      {unloadDialog && (
        <ConfirmDialog
          title="Unload first?"
          body={
            <>
              <strong>{model.name}</strong> is currently active.
              Unload it before deleting from cache.
            </>
          }
          confirmLabel="Unload"
          onConfirm={async () => {
            try {
              await modelsApi.unload();
              setUnloadDialog(false);
              setDeleteDialog(true);
            } catch (e: any) {
              setDeleteError(String(e?.message ?? e));
              setUnloadDialog(false);
            }
          }}
          onCancel={() => setUnloadDialog(false)}
        />
      )}
    </div>
  );
}

function MenuItem({ icon, label, onClick, destructive = false }: { icon: React.ReactNode; label: string; onClick: () => void; destructive?: boolean }) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      style={{
        width: "100%",
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 12px",
        background: "transparent",
        border: "none",
        textAlign: "left",
        color: destructive ? "var(--error)" : "var(--text-secondary)",
        fontSize: 12,
        cursor: "pointer",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-surface)")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      {icon}
      {label}
    </button>
  );
}

// ── Compact variant (single row, reserved for dense lists) ─────────────

function renderCompact(args: {
  model: ModelInfo;
  color: string;
  isActive: boolean;
  isBusy: boolean;
  isError: boolean;
  dl: ReturnType<typeof useDownloads>["downloads"][string] | undefined;
  startDownload: (id: string, backend: "mlx" | "hf") => void;
  cancelDownload: (id: string) => void;
}) {
  const { model, color, isActive, isBusy, isError, dl, startDownload, cancelDownload } = args;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        border: "1px solid var(--border-subtle)",
        borderRadius: 8,
        background: "var(--bg-secondary)",
      }}
    >
      <div style={{ width: 8, height: 8, borderRadius: "50%", background: color, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: "var(--text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {model.name}
        </div>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {[model.author, model.parameters, model.size_label || model.size].filter(Boolean).join(" · ")}
        </div>
      </div>
      <ActionRow
        model={model}
        isActive={isActive}
        isBusy={isBusy}
        isError={isError}
        dl={dl}
        onStart={() => startDownload(model.id, model.backend)}
        onCancel={() => cancelDownload(model.id)}
      />
    </div>
  );
}

// ── Shared: action row ─────────────────────────────────────────────────

function ActionRow({
  model, isActive, isBusy, isError, dl, onStart, onCancel,
}: {
  model: ModelInfo;
  isActive: boolean;
  isBusy: boolean;
  isError: boolean;
  dl: ReturnType<typeof useDownloads>["downloads"][string] | undefined;
  onStart: () => void;
  onCancel: () => void;
}) {
  if (isBusy && dl) {
    const pct = Math.max(dl.progress * 100, 2);
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 10, width: "100%" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {dl.message || (dl.status === "loading" ? "Loading..." : "Downloading...")}
          </div>
          <div style={{ height: 3, borderRadius: 2, background: "var(--bg-primary)", overflow: "hidden" }}>
            <div
              style={{
                height: "100%",
                width: `${pct}%`,
                background: "var(--accent)",
                borderRadius: 2,
                transition: "width 300ms ease-out",
              }}
            />
          </div>
        </div>
        <button onClick={onCancel} title="Cancel" style={iconBtnStyle}>
          <XIcon size={14} />
        </button>
      </div>
    );
  }

  if (isError) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 10, width: "100%" }}>
        <span style={{ flex: 1, fontSize: 11, color: "var(--error)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {dl?.error || "Failed"}
        </span>
        <button onClick={onStart} style={{ ...secondaryBtnStyle, color: "var(--error)", borderColor: "rgba(229,83,75,0.3)" }}>
          Retry
        </button>
      </div>
    );
  }

  if (isActive) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8, width: "100%" }}>
        <span
          style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            fontSize: 12, padding: "5px 10px", borderRadius: 6,
            background: "var(--success-muted)", color: "var(--success)",
            fontWeight: 500,
          }}
        >
          <Check size={12} /> Active
        </span>
        {model.hf_url && (
          <>
            <div style={{ flex: 1 }} />
            <a href={model.hf_url} target="_blank" rel="noreferrer" style={linkStyle} title="View on HuggingFace">
              <ExternalLink size={12} />
            </a>
          </>
        )}
      </div>
    );
  }

  if (model.is_cached) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8, width: "100%" }}>
        <button onClick={onStart} style={primaryBtnStyle}>
          Load model
        </button>
        <div style={{ flex: 1 }} />
        {model.hf_url && (
          <a href={model.hf_url} target="_blank" rel="noreferrer" style={linkStyle} title="View on HuggingFace">
            <ExternalLink size={12} />
          </a>
        )}
      </div>
    );
  }

  // Not cached, not in-flight
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, width: "100%" }}>
      <button onClick={onStart} style={primaryBtnStyle}>
        <Download size={12} style={{ marginRight: 6 }} />
        Download
      </button>
      <div style={{ flex: 1 }} />
      {model.hf_url && (
        <a href={model.hf_url} target="_blank" rel="noreferrer" style={linkStyle} title="View on HuggingFace">
          <ExternalLink size={12} />
        </a>
      )}
    </div>
  );
}

// ── Badges ────────────────────────────────────────────────────────────

function BackendBadge({ backend }: { backend: "mlx" | "hf" }) {
  return (
    <span
      style={{
        fontSize: 10, padding: "1px 6px", borderRadius: 3,
        background: "var(--bg-elevated)", color: "var(--text-tertiary)",
        fontWeight: 500,
        letterSpacing: "0.02em",
      }}
    >
      {backend === "mlx" ? "MLX" : "HF"}
    </span>
  );
}

function HeatIcon({ heat }: { heat?: string }) {
  if (heat === "Cool") return <Snowflake size={11} style={{ color: "#66d6e5" }} />;
  if (heat === "Warm") return <Thermometer size={11} style={{ color: "#e5a820" }} />;
  if (heat === "Hot") return <Flame size={11} style={{ color: "#e5534b" }} />;
  return null;
}

function ToolUseBadge({ tier }: { tier?: "verified" | "likely" | "unknown" }) {
  if (!tier || tier === "unknown") return null;
  const isVerified = tier === "verified";
  const color = isVerified ? "var(--success)" : "var(--warning)";
  const label = isVerified ? "Tools ✓" : "Tools?";
  const title = isVerified
    ? "Verified tool-use support — curated by the harness team"
    : "Likely tool-use support — chat template references tools/functions";
  return (
    <span
      title={title}
      style={{
        display: "inline-flex", alignItems: "center", gap: 3,
        fontSize: 10, padding: "1px 6px", borderRadius: 3,
        background: "var(--bg-elevated)", color,
        fontWeight: 500,
      }}
    >
      {isVerified ? <ShieldCheck size={10} /> : <HelpCircle size={10} />}
      {label}
    </span>
  );
}

function Sep({ text }: { text: string }) {
  return (
    <>
      <span style={{ color: "var(--text-muted)" }}>·</span>
      <span>{text}</span>
    </>
  );
}

// ── Styles ────────────────────────────────────────────────────────────

const primaryBtnStyle: React.CSSProperties = {
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
  transition: "background 60ms ease-out",
};

const secondaryBtnStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "5px 10px",
  background: "var(--bg-surface)",
  color: "var(--text-secondary)",
  border: "1px solid var(--border-default)",
  borderRadius: 6,
  fontSize: 12,
  cursor: "pointer",
};

const iconBtnStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: 24, height: 24,
  background: "transparent",
  color: "var(--text-muted)",
  border: "none",
  borderRadius: 4,
  cursor: "pointer",
};

const linkStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: 24, height: 24,
  color: "var(--text-muted)",
  textDecoration: "none",
  borderRadius: 4,
};
