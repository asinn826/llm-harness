import { useState, useEffect, useRef } from "react";
import { ChevronDown, Loader2, Cpu, Flame, Snowflake, Thermometer, Check } from "lucide-react";
import { models as modelsApi } from "../lib/api";
import type { ModelInfo } from "../lib/types";
import { getModelColor } from "../lib/types";

interface ModelSwitcherProps {
  onModelLoaded?: (modelId: string, backend: string) => void;
  collapsed?: boolean;
}

export function ModelSwitcher({ onModelLoaded, collapsed = false }: ModelSwitcherProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [recommended, setRecommended] = useState<ModelInfo[]>([]);
  const [cached, setCached] = useState<ModelInfo[]>([]);
  const [currentModel, setCurrentModel] = useState<string | null>(null);
  const [currentBackend, setCurrentBackend] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [loadProgress, setLoadProgress] = useState(0);
  const [loadMessage, setLoadMessage] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const fetchModels = async () => {
    try {
      const data = await modelsApi.list();
      setRecommended(data.recommended);
      setCached(data.cached);
      setCurrentModel(data.current);
      setCurrentBackend(data.current_backend);
    } catch {
      // silently fail
    }
  };

  useEffect(() => {
    fetchModels();
  }, []);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        if (!loading) setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [loading]);

  // Close dropdown when collapse state changes
  useEffect(() => {
    setIsOpen(false);
  }, [collapsed]);

  const handleSelect = (modelId: string, backend: string) => {
    if (modelId === currentModel) {
      setIsOpen(false);
      return;
    }

    setLoading(modelId);
    setLoadProgress(0);
    setLoadMessage("Connecting...");
    setLoadError(null);

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/models/load`);

    ws.onopen = () => {
      ws.send(JSON.stringify({ model_id: modelId, backend }));
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case "progress":
          setLoadProgress(msg.progress);
          setLoadMessage(msg.message);
          break;
        case "done":
          setCurrentModel(msg.model_id);
          setCurrentBackend(msg.backend);
          setLoading(null);
          setLoadProgress(0);
          setLoadMessage("");
          setIsOpen(false);
          onModelLoaded?.(msg.model_id, msg.backend);
          fetchModels();
          ws.close();
          break;
        case "error":
          setLoadError(msg.message);
          setLoading(null);
          setLoadProgress(0);
          setLoadMessage("");
          ws.close();
          break;
      }
    };

    ws.onerror = () => {
      setLoadError("Connection failed");
      setLoading(null);
    };
  };

  const modelColor = currentModel ? getModelColor(currentModel) : "var(--text-muted)";

  const HeatIcon = ({ heat }: { heat?: string }) => {
    if (heat === "Cool") return <Snowflake size={11} className="text-cyan-400" />;
    if (heat === "Warm") return <Thermometer size={11} className="text-amber-400" />;
    if (heat === "Hot") return <Flame size={11} className="text-red-400" />;
    return null;
  };

  // ── Dropdown (shared between collapsed and expanded) ──────────────

  const dropdown = isOpen && !loading && (
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
      <div className="px-2.5 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
        Recommended
      </div>
      {recommended.map((model) => (
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
            <div className="text-xs text-[var(--text-primary)] flex items-center gap-1.5">
              {model.name}
              <span className="text-[10px] px-1 py-px rounded bg-[var(--bg-elevated)] text-[var(--text-tertiary)]">
                {model.backend === "mlx" ? "MLX" : "HF"}
              </span>
              <HeatIcon heat={model.heat} />
            </div>
            <div className="text-[10px] text-[var(--text-muted)]">
              {model.quality} · {model.size}
            </div>
          </div>
          {model.is_loaded && <Check size={14} className="text-[var(--success)] shrink-0" />}
        </button>
      ))}

      {cached.length > 0 && (
        <>
          <div className="px-2.5 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wider border-t border-[var(--border-subtle)]">
            Locally cached
          </div>
          {cached.map((model) => (
            <button
              key={model.id}
              onClick={() => handleSelect(model.id, model.backend)}
              className="w-full flex items-center gap-2.5 px-2.5 py-2 hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
            >
              <Cpu size={14} className="text-[var(--text-muted)] shrink-0" />
              <div className="flex-1 text-left min-w-0">
                <div className="text-xs text-[var(--text-secondary)] truncate">{model.name}</div>
              </div>
              {model.is_loaded && <Check size={14} className="text-[var(--success)] shrink-0" />}
            </button>
          ))}
        </>
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
          title={currentModel ? currentModel.split("/").pop() : "Select model"}
        >
          {loading ? (
            <Loader2 size={16} className="text-[var(--accent)] animate-spin" />
          ) : (
            <div
              className="w-3 h-3 rounded-full"
              style={{ background: modelColor }}
            />
          )}
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
          className="w-2 h-2 rounded-full shrink-0"
          style={{ background: modelColor }}
        />
        <div className="flex-1 text-left min-w-0">
          {loading ? (
            <>
              <div className="text-xs text-[var(--text-primary)] font-medium truncate">
                {loading.split("/").pop()}
              </div>
              <div className="text-[10px] text-[var(--text-tertiary)]">
                {loadMessage || "Loading..."}
              </div>
              <div className="mt-1 h-1 w-full bg-[var(--bg-primary)] rounded-full overflow-hidden">
                <div
                  className="h-full bg-[var(--accent)] rounded-full transition-all duration-300 ease-out"
                  style={{ width: `${Math.max(loadProgress * 100, 2)}%` }}
                />
              </div>
            </>
          ) : (
            <>
              <div className="text-xs text-[var(--text-primary)] font-medium truncate">
                {currentModel ? currentModel.split("/").pop() : "No model"}
              </div>
              {currentModel && !loadError && (
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
        {loading ? (
          <Loader2 size={14} className="text-[var(--accent)] animate-spin" />
        ) : (
          <ChevronDown size={14} className="text-[var(--text-muted)]" />
        )}
      </button>
      {dropdown}
    </div>
  );
}
