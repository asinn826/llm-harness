import { useState, useEffect } from "react";
import {
  Search,
  Loader2,
  Check,
  Download,
  Trash2,
  ExternalLink,
  Cpu,
  Flame,
  Snowflake,
  Thermometer,
  HardDrive,
} from "lucide-react";
import { models as modelsApi } from "../lib/api";
import type { ModelInfo } from "../lib/types";
import { getModelColor } from "../lib/types";

interface ModelsViewProps {
  onModelLoaded: (modelId: string, backend: string) => void;
}

export function ModelsView({ onModelLoaded }: ModelsViewProps) {
  const [recommended, setRecommended] = useState<ModelInfo[]>([]);
  const [cached, setCached] = useState<ModelInfo[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState<string | null>(null);
  const [currentModel, setCurrentModel] = useState<string | null>(null);

  const fetchModels = async () => {
    try {
      const data = await modelsApi.list();
      setRecommended(data.recommended);
      setCached(data.cached);
      setCurrentModel(data.current);
    } catch {
      // silently fail
    }
  };

  useEffect(() => {
    fetchModels();
  }, []);

  const handleLoad = async (modelId: string, backend: string) => {
    setLoading(modelId);
    try {
      const result = await modelsApi.load(modelId, backend);
      setCurrentModel(result.model.model_id);
      onModelLoaded(result.model.model_id, result.model.backend);
      await fetchModels();
    } catch (err) {
      console.error("Failed to load model:", err);
    } finally {
      setLoading(null);
    }
  };

  const filteredRecommended = recommended.filter(
    (m) =>
      !search ||
      m.name.toLowerCase().includes(search.toLowerCase()) ||
      m.id.toLowerCase().includes(search.toLowerCase())
  );

  const filteredCached = cached.filter(
    (m) =>
      !search ||
      m.name.toLowerCase().includes(search.toLowerCase()) ||
      m.id.toLowerCase().includes(search.toLowerCase())
  );

  const HeatBadge = ({ heat }: { heat?: string }) => {
    if (heat === "Cool")
      return (
        <span className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400">
          <Snowflake size={10} /> Cool
        </span>
      );
    if (heat === "Warm")
      return (
        <span className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400">
          <Thermometer size={10} /> Warm
        </span>
      );
    if (heat === "Hot")
      return (
        <span className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-400">
          <Flame size={10} /> Hot
        </span>
      );
    return null;
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto py-6 px-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-lg font-semibold text-[var(--text-primary)]">Models</h1>
        </div>

        {/* Search */}
        <div className="relative mb-6">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search models..."
            className="w-full pl-9 pr-4 py-2.5 bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-lg text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--accent)] transition-colors duration-[var(--duration-fast)]"
          />
        </div>

        {/* Recommended */}
        <div className="mb-8">
          <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-3 font-medium">
            Recommended
          </div>
          <div className="space-y-2">
            {filteredRecommended.map((model) => (
              <div
                key={model.id}
                className="flex items-center gap-3 p-3 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border-subtle)] hover:border-[var(--border-default)] transition-colors duration-[var(--duration-fast)]"
              >
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                  style={{ background: `${getModelColor(model.id)}15` }}
                >
                  <Cpu size={18} style={{ color: getModelColor(model.id) }} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-[var(--text-primary)]">
                      {model.name}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-elevated)] text-[var(--text-tertiary)]">
                      {model.backend === "mlx" ? "MLX" : "HF"}
                    </span>
                    <HeatBadge heat={model.heat} />
                  </div>
                  <div className="text-xs text-[var(--text-muted)] mt-0.5">
                    {model.quality} · {model.size}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {model.is_cached ? (
                    <span className="text-[10px] text-[var(--success)]">Cached</span>
                  ) : (
                    <span className="text-[10px] text-[var(--text-muted)]">Not cached</span>
                  )}
                  {model.is_loaded ? (
                    <span className="flex items-center gap-1 text-xs text-[var(--success)] bg-[var(--success-muted)] px-2.5 py-1 rounded-md font-medium">
                      <Check size={12} /> Loaded
                    </span>
                  ) : (
                    <button
                      onClick={() => handleLoad(model.id, model.backend)}
                      disabled={loading !== null}
                      className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-md font-medium transition-colors duration-[var(--duration-fast)] disabled:opacity-50 bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)]"
                    >
                      {loading === model.id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : model.is_cached ? (
                        "Load"
                      ) : (
                        <>
                          <Download size={12} /> Download
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Cached */}
        {filteredCached.length > 0 && (
          <div className="mb-8">
            <div className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider mb-3 font-medium">
              Locally Cached
            </div>
            <div className="space-y-2">
              {filteredCached.map((model) => (
                <div
                  key={model.id}
                  className="flex items-center gap-3 p-3 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border-subtle)] hover:border-[var(--border-default)] transition-colors duration-[var(--duration-fast)]"
                >
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0 bg-[var(--bg-surface)]">
                    <Cpu size={18} className="text-[var(--text-muted)]" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-[var(--text-secondary)] truncate">{model.id}</div>
                    <div className="text-xs text-[var(--text-muted)] mt-0.5">
                      {model.backend === "mlx" ? "MLX" : "HF"}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {model.is_loaded ? (
                      <span className="flex items-center gap-1 text-xs text-[var(--success)] bg-[var(--success-muted)] px-2.5 py-1 rounded-md font-medium">
                        <Check size={12} /> Loaded
                      </span>
                    ) : (
                      <button
                        onClick={() => handleLoad(model.id, model.backend)}
                        disabled={loading !== null}
                        className="text-xs px-2.5 py-1 rounded-md font-medium bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)] disabled:opacity-50"
                      >
                        {loading === model.id ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : (
                          "Load"
                        )}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Footer stats */}
        <div className="flex items-center gap-3 text-[10px] text-[var(--text-muted)] pt-4 border-t border-[var(--border-subtle)]">
          <HardDrive size={12} />
          <span>{recommended.filter((m) => m.is_cached).length + cached.length} models cached</span>
          <span>·</span>
          <span>~/.cache/huggingface</span>
        </div>
      </div>
    </div>
  );
}
