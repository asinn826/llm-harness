import { useState, useEffect, useRef } from "react";
import { ChevronDown, Loader2, Cpu, Check, ArrowRight } from "lucide-react";
import { models as modelsApi } from "../lib/api";
import type { ModelInfo } from "../lib/types";
import { getModelColor } from "../lib/types";
import { useDownloads } from "../contexts/DownloadsContext";

interface ModelSwitcherProps {
  onBrowseAll?: () => void;
  collapsed?: boolean;
}

export function ModelSwitcher({ onBrowseAll, collapsed = false }: ModelSwitcherProps) {
  const { downloads, currentModelId, currentBackend, startDownload } = useDownloads();

  const [isOpen, setIsOpen] = useState(false);
  const [cached, setCached] = useState<ModelInfo[]>([]);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Any in-flight load (from here or from the Models page) shows progress
  // in the trigger. Priority: loads started from the sidebar itself > any.
  const activeDownload = Object.values(downloads).find(
    (d) => d.status === "downloading" || d.status === "loading"
  );
  const loadingId = activeDownload?.modelId ?? null;
  const loadProgress = activeDownload?.progress ?? 0;
  const loadMessage = activeDownload?.message ?? "";
  const loadError = Object.values(downloads).find((d) => d.status === "error")?.error ?? null;

  const fetchModels = async () => {
    try {
      const data = await modelsApi.list();
      // Sidebar is pure quick-switch: union of recommended + cached,
      // but only models that are cached locally. Recommended models that
      // aren't cached live on the Models page.
      const quick = [
        ...data.recommended.filter((m) => m.is_cached),
        ...data.cached,
      ];
      // De-dup by id while preserving order
      const seen = new Set<string>();
      setCached(quick.filter((m) => (seen.has(m.id) ? false : seen.add(m.id))));
    } catch {
      // silently fail
    }
  };

  useEffect(() => {
    fetchModels();
  }, [currentModelId]); // refresh list whenever the active model changes

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        if (!loadingId) setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [loadingId]);

  useEffect(() => {
    setIsOpen(false);
  }, [collapsed]);

  const handleSelect = (modelId: string, backend: string) => {
    if (modelId === currentModelId) {
      setIsOpen(false);
      return;
    }
    startDownload(modelId, backend as "mlx" | "hf");
    setIsOpen(false);
  };

  const handleBrowseAll = () => {
    setIsOpen(false);
    onBrowseAll?.();
  };

  const modelColor = currentModelId ? getModelColor(currentModelId) : "var(--text-muted)";

  // ── Dropdown ──────────────────────────────────────────────────────

  const dropdown = isOpen && !loadingId && (
    <div
      ref={dropdownRef}
      style={collapsed ? {
        position: "fixed",
        left: 52,
        top: triggerRef.current?.getBoundingClientRect().top ?? 80,
        zIndex: 100,
        width: 260,
      } : {
        position: "absolute",
        left: 12,
        right: 12,
        top: "100%",
        marginTop: 4,
        zIndex: 50,
      }}
      className="bg-[var(--bg-tertiary)] border border-[var(--border-default)] rounded-lg shadow-lg overflow-hidden"
    >
      {cached.length === 0 ? (
        <div className="px-3 py-6 text-center">
          <div className="text-xs text-[var(--text-secondary)] mb-1">No models yet</div>
          <div className="text-[10px] text-[var(--text-muted)]">Browse to download one</div>
        </div>
      ) : (
        <>
          <div className="px-2.5 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
            Available
          </div>
          {cached.map((model) => (
            <button
              key={model.id}
              onClick={() => handleSelect(model.id, model.backend)}
              className="w-full flex items-center gap-2.5 px-2.5 py-2 hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
            >
              <div
                className="w-2 h-2 rounded-full shrink-0"
                style={{ background: getModelColor(model.id) }}
              />
              <div className="flex-1 text-left min-w-0">
                <div className="text-xs text-[var(--text-primary)] flex items-center gap-1.5 truncate">
                  <span className="truncate">{model.name}</span>
                  <span className="text-[10px] px-1 py-px rounded bg-[var(--bg-elevated)] text-[var(--text-tertiary)] shrink-0">
                    {model.backend === "mlx" ? "MLX" : "HF"}
                  </span>
                </div>
                {(model.quality || model.size_label || model.size) && (
                  <div className="text-[10px] text-[var(--text-muted)] truncate">
                    {[model.quality, model.size_label || model.size].filter(Boolean).join(" · ")}
                  </div>
                )}
              </div>
              {model.is_loaded && <Check size={14} className="text-[var(--success)] shrink-0" />}
            </button>
          ))}
        </>
      )}

      {/* Browse all footer */}
      {onBrowseAll && (
        <button
          onClick={handleBrowseAll}
          className="w-full flex items-center gap-2 px-2.5 py-2.5 border-t border-[var(--border-subtle)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
        >
          <span className="flex-1 text-left text-[11px] text-[var(--text-secondary)] font-medium">
            Browse all models
          </span>
          <ArrowRight size={12} className="text-[var(--text-muted)]" />
        </button>
      )}
    </div>
  );

  // ── Collapsed: icon-only trigger ──────────────────────────────────

  if (collapsed) {
    return (
      <div className="relative flex justify-center py-1">
        <button
          ref={triggerRef}
          onClick={() => setIsOpen(!isOpen)}
          className="w-9 h-9 flex items-center justify-center rounded-md hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
          title={loadingId ? `Loading ${loadingId.split("/").pop()}...` : currentModelId ? currentModelId.split("/").pop() : "Select model"}
        >
          <div
            className={loadingId ? "model-dot-loading" : ""}
            style={{
              width: 12,
              height: 12,
              borderRadius: "50%",
              background: loadingId ? "var(--accent)" : modelColor,
              color: loadingId ? "var(--accent)" : modelColor,
              transition: "background 300ms ease-out",
            }}
          />
        </button>
        {dropdown}
      </div>
    );
  }

  // ── Expanded: full trigger with model info ────────────────────────

  return (
    <div className="relative px-3 py-2 border-b border-[var(--border-subtle)]">
      <button
        ref={triggerRef}
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-2 px-2.5 py-2 rounded-md bg-[var(--bg-surface)] hover:bg-[var(--bg-elevated)] transition-colors duration-[var(--duration-fast)]"
      >
        <div
          className={loadingId ? "model-dot-loading" : ""}
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: loadingId ? "var(--accent)" : modelColor,
            color: loadingId ? "var(--accent)" : modelColor,
            flexShrink: 0,
            transition: "background 300ms ease-out",
          }}
        />
        <div className="flex-1 text-left min-w-0">
          {loadingId ? (
            <>
              <div className="text-xs text-[var(--text-primary)] font-medium truncate">
                {loadingId.split("/").pop()}
              </div>
              <div className="text-[10px] text-[var(--text-tertiary)]">
                {loadMessage || "Loading..."}
              </div>
              <div className="shimmer-bar mt-1.5 w-full" style={{ opacity: loadProgress > 0 ? 0 : 1, transition: "opacity 300ms" }} />
              <div className="mt-1 h-[3px] w-full bg-[var(--bg-primary)] rounded-full overflow-hidden" style={{ opacity: loadProgress > 0 ? 1 : 0, transition: "opacity 300ms" }}>
                <div
                  className="h-full bg-[var(--accent)] rounded-full transition-all duration-300 ease-out"
                  style={{ width: `${Math.max(loadProgress * 100, 2)}%` }}
                />
              </div>
            </>
          ) : (
            <>
              <div className="text-xs text-[var(--text-primary)] font-medium truncate">
                {currentModelId ? currentModelId.split("/").pop() : "No model"}
              </div>
              {currentModelId && !loadError && (
                <div className="text-[10px] text-[var(--text-tertiary)] flex items-center gap-1">
                  <span>{currentBackend === "mlx" ? "MLX" : "HF"}</span>
                  <span>·</span>
                  <span className="text-[var(--success)]">Ready</span>
                </div>
              )}
              {loadError && (
                <div className="text-[10px] text-[var(--error)] truncate">{loadError}</div>
              )}
            </>
          )}
        </div>
        {loadingId ? (
          <Loader2 size={14} className="text-[var(--accent)] animate-spin" />
        ) : (
          <ChevronDown size={14} className="text-[var(--text-muted)]" />
        )}
      </button>
      {dropdown}
    </div>
  );
}
