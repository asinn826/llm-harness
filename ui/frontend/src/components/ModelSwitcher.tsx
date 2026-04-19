import { useState, useEffect, useRef } from "react";
import { ChevronDown, Loader2, Cpu, Flame, Snowflake, Thermometer, Check } from "lucide-react";
import { models as modelsApi } from "../lib/api";
import type { ModelInfo } from "../lib/types";
import { getModelColor } from "../lib/types";

interface ModelSwitcherProps {
  onModelLoaded?: (modelId: string, backend: string) => void;
}

export function ModelSwitcher({ onModelLoaded }: ModelSwitcherProps) {
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

  const handleSelect = (modelId: string, backend: string) => {
    if (modelId === currentModel) {
      setIsOpen(false);
      return;
    }

    setLoading(modelId);
    setLoadProgress(0);
    setLoadMessage("Connecting...");
    setLoadError(null);

    // Use WebSocket for progress-streamed loading
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

  const currentDisplay = currentModel
    ? currentModel.split("/").pop() || currentModel
    : "No model";

  const HeatIcon = ({ heat }: { heat?: string }) => {
    if (heat === "Cool") return <Snowflake size={11} className="text-cyan-400" />;
    if (heat === "Warm") return <Thermometer size={11} className="text-amber-400" />;
    if (heat === "Hot") return <Flame size={11} className="text-red-400" />;
    return null;
  };

  return (
    <div ref={dropdownRef} className="relative px-3 py-2 border-b border-[var(--border-subtle)]">
      {/* Trigger */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-2 px-2.5 py-2 rounded-md bg-[var(--bg-surface)] hover:bg-[var(--bg-elevated)] transition-colors duration-[var(--duration-fast)]"
      >
        <div
          className="w-2 h-2 rounded-full shrink-0"
          style={{ background: currentModel ? getModelColor(currentModel) : "var(--text-muted)" }}
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
              {/* Progress bar */}
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
                {currentDisplay}
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

      {/* Dropdown */}
      {isOpen && !loading && (
        <div className="absolute left-3 right-3 top-full mt-1 z-50 bg-[var(--bg-tertiary)] border border-[var(--border-default)] rounded-lg shadow-lg overflow-hidden">
          {/* Recommended */}
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

          {/* Cached */}
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
      )}
    </div>
  );
}
