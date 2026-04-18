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
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSelect = async (modelId: string, backend: string) => {
    if (modelId === currentModel) {
      setIsOpen(false);
      return;
    }
    setLoading(modelId);
    try {
      const result = await modelsApi.load(modelId, backend);
      setCurrentModel(result.model.model_id);
      setCurrentBackend(result.model.backend);
      onModelLoaded?.(result.model.model_id, result.model.backend);
    } catch (err) {
      console.error("Failed to load model:", err);
    } finally {
      setLoading(null);
      setIsOpen(false);
    }
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
          <div className="text-xs text-[var(--text-primary)] font-medium truncate">
            {loading ? "Loading..." : currentDisplay}
          </div>
          {currentModel && (
            <div className="text-[10px] text-[var(--text-tertiary)] flex items-center gap-1">
              <span>{currentBackend === "mlx" ? "MLX" : "HF"}</span>
              <span>·</span>
              <span className="text-[var(--success)]">Ready</span>
            </div>
          )}
        </div>
        {loading ? (
          <Loader2 size={14} className="text-[var(--text-muted)] animate-spin" />
        ) : (
          <ChevronDown size={14} className="text-[var(--text-muted)]" />
        )}
      </button>

      {/* Dropdown */}
      {isOpen && (
        <div className="absolute left-3 right-3 top-full mt-1 z-50 bg-[var(--bg-tertiary)] border border-[var(--border-default)] rounded-lg shadow-lg overflow-hidden">
          {/* Recommended */}
          <div className="px-2.5 py-1.5 text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
            Recommended
          </div>
          {recommended.map((model) => (
            <button
              key={model.id}
              onClick={() => handleSelect(model.id, model.backend)}
              disabled={loading !== null}
              className="w-full flex items-center gap-2.5 px-2.5 py-2 hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)] disabled:opacity-50"
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
              {loading === model.id && <Loader2 size={14} className="text-[var(--accent)] animate-spin shrink-0" />}
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
                  disabled={loading !== null}
                  className="w-full flex items-center gap-2.5 px-2.5 py-2 hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)] disabled:opacity-50"
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
