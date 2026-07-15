/**
 * ModelsView — full-page model browse/discover/download experience.
 *
 * Tabs:
 *   - Library: Recommended (starred) + Downloaded cards
 *   - Hub:     HuggingFace Hub search (opt-in via one-time disclosure)
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Search, Lock, AlertCircle, Globe, ArrowLeft, X } from "lucide-react";
import { models as modelsApi, prefs as prefsApi } from "../lib/api";
import type { ComparisonModelInput, ModelInfo, HubSearchResult, ModelUpdateInfo } from "../lib/types";
import { ModelCard } from "../components/ModelCard";
import { ModelDetailsDrawer } from "../components/ModelDetailsDrawer";
import { useDownloads } from "../contexts/DownloadsContext";
import { getTransferKey } from "../lib/transfers";

type Tab = "library" | "hub";
type SortOpt = "downloads" | "likes" | "lastModified" | "trending";
type BackendFilter = "all" | "mlx" | "hf";

interface DrawerState {
  modelId: string;
  backend: "mlx" | "hf";
  isCached: boolean;
  gated: boolean;
}

interface ModelsViewProps {
  mode?: "browse" | "add-to-comparison";
  initialTab?: Tab;
  draftModels?: ComparisonModelInput[];
  maxModels?: number;
  onAddModel?: (model: ComparisonModelInput) => void;
  onRemoveModel?: (modelId: string) => void;
  onReturn?: () => void;
}

export function ModelsView({
  mode = "browse",
  initialTab = "library",
  draftModels = [],
  maxModels = 3,
  onAddModel,
  onRemoveModel,
  onReturn,
}: ModelsViewProps) {
  const [tab, setTab] = useState<Tab>(initialTab);

  // Library state
  const [recommended, setRecommended] = useState<ModelInfo[]>([]);
  const [cached, setCached] = useState<ModelInfo[]>([]);
  const [libLoading, setLibLoading] = useState(true);
  const [updates, setUpdates] = useState<Record<string, ModelUpdateInfo>>({});

  // Hub state
  const [hubEnabled, setHubEnabled] = useState(false);
  const [disclosureOpen, setDisclosureOpen] = useState(false);
  const [hubResults, setHubResults] = useState<HubSearchResult[]>([]);
  const [hubLoading, setHubLoading] = useState(false);
  const [hubError, setHubError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortOpt>("downloads");
  const [backendFilter, setBackendFilter] = useState<BackendFilter>("all");

  // Drawer
  const [drawer, setDrawer] = useState<DrawerState | null>(null);

  const { downloads, subscribe } = useDownloads();
  const selecting = mode === "add-to-comparison";

  // Load prefs on mount (is Hub search enabled?)
  useEffect(() => {
    prefsApi.get().then((p) => {
      setHubEnabled(p.hub_search_enabled);
      if (initialTab === "hub" && !p.hub_search_enabled) setDisclosureOpen(true);
    }).catch(() => {});
  }, [initialTab]);

  // Library refresh
  const refreshLibrary = useCallback(async () => {
    try {
      const data = await modelsApi.list();
      setRecommended(data.recommended);
      setCached(data.cached);
    } catch {
      // silent
    } finally {
      setLibLoading(false);
    }

    // Fetch update status in the background — don't block render.
    modelsApi.updates()
      .then((list) => {
        const map: Record<string, ModelUpdateInfo> = {};
        for (const u of list) map[u.id] = u;
        setUpdates(map);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void refreshLibrary(); }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshLibrary]);

  // Refetch library when a download completes
  useEffect(() => {
    return subscribe((event) => {
      if (event.type === "completed") {
        refreshLibrary();
        setHubResults((current) => current.map((result) =>
          result.id === event.modelId ? { ...result, is_cached: true } : result
        ));
      }
    });
  }, [subscribe, refreshLibrary]);

  // Hub search with debounce
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hubSearchRequestRef = useRef(0);
  const runHubSearch = useCallback((requestId: number) => {
    if (!hubEnabled || tab !== "hub") return;
    setHubLoading(true);
    setHubError(null);
    modelsApi
      .search({ q: query, sort, backend: backendFilter, limit: 30 })
      .then((data) => {
        if (hubSearchRequestRef.current !== requestId) return;
        setHubResults(data.results);
        setHubError(data.error ?? null);
      })
      .catch((e) => {
        if (hubSearchRequestRef.current === requestId) setHubError(String(e));
      })
      .finally(() => {
        if (hubSearchRequestRef.current === requestId) setHubLoading(false);
      });
  }, [hubEnabled, tab, query, sort, backendFilter]);

  useEffect(() => {
    const requestId = ++hubSearchRequestRef.current;
    if (tab !== "hub" || !hubEnabled) return;
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => runHubSearch(requestId), 350);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, [tab, hubEnabled, query, sort, backendFilter, runHubSearch]);

  const handleHubTabClick = () => {
    if (hubEnabled) setTab("hub");
    else setDisclosureOpen(true);
  };

  const handleAcceptDisclosure = async () => {
    try {
      await prefsApi.setHubSearch(true);
      setHubEnabled(true);
      setDisclosureOpen(false);
      setTab("hub");
    } catch {
      setDisclosureOpen(false);
    }
  };

  // ── Library sorted views ────────────────────────────────────────
  const recommendedSorted = useMemo(() => {
    return [...recommended].sort((a, b) => {
      const aScore = (a.is_loaded ? 2 : 0) + (a.is_cached ? 1 : 0);
      const bScore = (b.is_loaded ? 2 : 0) + (b.is_cached ? 1 : 0);
      return bScore - aScore;
    });
  }, [recommended]);

  const cachedSorted = useMemo(() => {
    return [...cached].sort((a, b) => (b.last_used ?? 0) - (a.last_used ?? 0));
  }, [cached]);

  // ── Drawer openers ──────────────────────────────────────────────
  const openDrawer = (d: DrawerState) => setDrawer(d);
  const closeDrawer = () => setDrawer(null);
  const selectedIds = new Set(draftModels.map((model) => model.model_id));

  return (
    <div className="models-view" style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "hidden" }}>
      {/* Header */}
      <div className="models-header">
        <h1 className="page-title">{selecting ? "Choose models" : "Models"}</h1>
        {selecting && <span className="header-count">{draftModels.length} / {maxModels}</span>}
        <div style={{ flex: 1 }} />
        {selecting && onReturn && (
          <button onClick={onReturn} style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            padding: "6px 10px", borderRadius: 6,
            border: "1px solid var(--border-default)", background: "var(--bg-secondary)",
            color: "var(--text-secondary)", fontSize: 12, cursor: "pointer",
          }}>
            <ArrowLeft size={13} /> Return to comparison
          </button>
        )}
      </div>

      {selecting && draftModels.length > 0 && (
        <div style={{
          display: "flex", alignItems: "center", gap: 8, minHeight: 42,
          padding: "7px 32px", borderBottom: "1px solid var(--border-subtle)",
          background: "var(--bg-secondary)", flexShrink: 0,
        }}>
          {draftModels.map((model) => {
            const transfer = downloads[getTransferKey(
              model.model_id,
              model.backend,
              model.revision,
            )];
            const state = transfer?.status === "error"
              ? "Failed"
              : transfer && (transfer.status === "downloading" || transfer.status === "loading")
                ? `${Math.round(transfer.progress * 100)}%`
                : "Ready";
            return (
              <span key={model.model_id} title={model.model_id} style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                padding: "4px 8px", borderRadius: 999,
                border: "1px solid var(--border-default)", color: "var(--text-secondary)",
                background: "var(--bg-tertiary)", fontSize: 11,
              }}>
                {model.model_id.split("/").pop()}
                <span style={{ color: state === "Failed" ? "var(--error)" : "var(--text-muted)", fontSize: 9 }}>{state}</span>
                {onRemoveModel && (
                  <button onClick={() => onRemoveModel(model.model_id)} aria-label={`Remove ${model.model_id}`} style={{
                    display: "flex", border: 0, padding: 0, background: "transparent", color: "var(--text-muted)", cursor: "pointer",
                  }}><X size={11} /></button>
                )}
              </span>
            );
          })}
          <div style={{ flex: 1 }} />
          {draftModels.length >= 2 && onReturn && (
            <button onClick={onReturn} style={{
              border: 0, borderRadius: 6, padding: "6px 10px", background: "var(--accent)", color: "white", fontSize: 11, fontWeight: 500, cursor: "pointer",
            }}>Compare {draftModels.length} models</button>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className="models-tabs" style={{ display: "flex", padding: "0 32px", borderBottom: "1px solid var(--border-subtle)", flexShrink: 0, gap: 4 }}>
        <TabButton active={tab === "library"} onClick={() => setTab("library")} label="Library" />
        <TabButton active={tab === "hub"} onClick={handleHubTabClick} label="Hub" />
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        <div className="models-content" style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 32px" }}>
          {tab === "library" && (
            <LibraryPane
              loading={libLoading}
              recommended={recommendedSorted}
              cached={cachedSorted}
              updates={updates}
              selectionMode={selecting}
              onRefresh={refreshLibrary}
              onOpenDrawer={(m) => openDrawer({
                modelId: m.id,
                backend: m.backend,
                isCached: m.is_cached,
                gated: false,
              })}
            />
          )}
          {tab === "hub" && (
            <HubPane
              query={query} onQueryChange={setQuery}
              sort={sort} onSortChange={setSort}
              backendFilter={backendFilter} onBackendFilterChange={setBackendFilter}
              loading={hubLoading}
              error={hubError}
              results={hubResults}
              onOpenDrawer={(r) => openDrawer({
                modelId: r.id,
                backend: r.backend_hint,
                isCached: r.is_cached,
                gated: r.gated,
              })}
            />
          )}
        </div>
      </div>

      {/* Disclosure */}
      {disclosureOpen && (
        <HubDisclosure
          onAccept={handleAcceptDisclosure}
          onCancel={() => { setDisclosureOpen(false); setTab("library"); }}
        />
      )}

      {/* Details drawer */}
      {drawer && (
        <ModelDetailsDrawer
          modelId={drawer.modelId}
          backend={drawer.backend}
          isCached={drawer.isCached}
          gated={drawer.gated}
          selectionMode={selecting}
          isSelected={selectedIds.has(drawer.modelId)}
          selectionFull={draftModels.length >= maxModels && !selectedIds.has(drawer.modelId)}
          onAddToComparison={onAddModel}
          onRemoveFromComparison={onRemoveModel}
          onClose={closeDrawer}
        />
      )}
    </div>
  );
}

// ── Library pane ────────────────────────────────────────────────────────

function LibraryPane({
  loading, recommended, cached, updates, onRefresh, onOpenDrawer,
  selectionMode,
}: {
  loading: boolean;
  recommended: ModelInfo[];
  cached: ModelInfo[];
  updates: Record<string, ModelUpdateInfo>;
  selectionMode: boolean;
  onRefresh: () => void;
  onOpenDrawer: (m: ModelInfo) => void;
}) {
  if (loading) return <SkeletonGrid count={4} />;

  const empty = recommended.length === 0 && cached.length === 0;

  return (
    <>
      {recommended.length > 0 && (
        <Section title="Recommended">
          <Grid>
            {recommended.map((m) => (
              <div key={m.id} onClick={(e) => {
                // Only open drawer when clicking on the card background, not action buttons
                if ((e.target as HTMLElement).closest("button, a")) return;
                onOpenDrawer(m);
              }} style={{ cursor: "pointer" }}>
                <ModelCard
                  model={m}
                  starred
                  hasUpdate={updates[m.id]?.has_update === true}
                  onDeleted={onRefresh}
                  onReview={selectionMode ? () => onOpenDrawer(m) : undefined}
                  reviewLabel="Review & add"
                />
              </div>
            ))}
          </Grid>
        </Section>
      )}
      {cached.length > 0 && (
        <Section title={`Downloaded (${cached.length})`}>
          <Grid>
            {cached.map((m) => (
              <div key={m.id} onClick={(e) => {
                if ((e.target as HTMLElement).closest("button, a")) return;
                onOpenDrawer(m);
              }} style={{ cursor: "pointer" }}>
                <ModelCard
                  model={m}
                  hasUpdate={updates[m.id]?.has_update === true}
                  onDeleted={onRefresh}
                  onReview={selectionMode ? () => onOpenDrawer(m) : undefined}
                  reviewLabel="Review & add"
                />
              </div>
            ))}
          </Grid>
        </Section>
      )}
      {empty && (
        <div style={{ padding: "48px 0", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
          No models available.
        </div>
      )}
    </>
  );
}

// ── Hub pane ────────────────────────────────────────────────────────────

function HubPane({
  query, onQueryChange,
  sort, onSortChange,
  backendFilter, onBackendFilterChange,
  loading, error, results, onOpenDrawer,
}: {
  query: string; onQueryChange: (v: string) => void;
  sort: SortOpt; onSortChange: (v: SortOpt) => void;
  backendFilter: BackendFilter; onBackendFilterChange: (v: BackendFilter) => void;
  loading: boolean; error: string | null;
  results: HubSearchResult[];
  onOpenDrawer: (r: HubSearchResult) => void;
}) {
  return (
    <>
      {/* Filter bar */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
        <div style={{ position: "relative", flex: "1 1 260px", minWidth: 200 }}>
          <Search size={13} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)" }} />
          <input
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Search HuggingFace..."
            style={{
              width: "100%",
              padding: "7px 10px 7px 30px",
              background: "var(--bg-secondary)",
              border: "1px solid var(--border-default)",
              borderRadius: 6,
              color: "var(--text-primary)",
              fontSize: 13,
              outline: "none",
              fontFamily: "inherit",
            }}
          />
        </div>
        <BackendToggle value={backendFilter} onChange={onBackendFilterChange} />
        <select
          value={sort}
          onChange={(e) => onSortChange(e.target.value as SortOpt)}
          style={{
            padding: "6px 10px",
            background: "var(--bg-secondary)",
            border: "1px solid var(--border-default)",
            borderRadius: 6,
            color: "var(--text-primary)",
            fontSize: 12,
            cursor: "pointer",
            outline: "none",
          }}
        >
          <option value="downloads">Most downloads</option>
          <option value="likes">Most likes</option>
          <option value="trending">Trending</option>
          <option value="lastModified">Recently updated</option>
        </select>
      </div>

      {/* Results */}
      {loading && <SkeletonGrid count={6} />}
      {error && !loading && (
        <ErrorBanner message={error} />
      )}
      {!loading && !error && results.length === 0 && (
        <div style={{ padding: "48px 0", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
          No results{query ? ` for "${query}"` : ""}.
        </div>
      )}
      {!loading && !error && results.length > 0 && (
        <Grid>
          {results.map((r) => (
            <div
              key={r.id}
              onClick={(e) => {
                if ((e.target as HTMLElement).closest("button, a")) return;
                onOpenDrawer(r);
              }}
              style={{ cursor: "pointer" }}
            >
              <HubResultCard result={r} onReview={() => onOpenDrawer(r)} />
            </div>
          ))}
        </Grid>
      )}
    </>
  );
}

function HubResultCard({ result, onReview }: { result: HubSearchResult; onReview: () => void }) {
  // Adapt HubSearchResult → ModelInfo-ish for the ModelCard
  const asModel: ModelInfo = {
    id: result.id,
    name: result.name,
    author: result.author,
    backend: result.backend_hint,
    tags: result.tags,
    hf_url: `https://huggingface.co/${result.id}`,
    tool_use_tier: result.tool_use_tier,
    is_cached: result.is_cached,
    is_loaded: false,
  };

  return (
    <div style={{ position: "relative" }}>
      <ModelCard model={asModel} variant="compact" onReview={onReview} reviewLabel="Check" />
      {/* Hub-specific stats overlay (below card content area) */}
      <div style={{
        position: "absolute",
        top: "50%", right: 88, transform: "translateY(-50%)",
        display: "flex", alignItems: "center", gap: 10,
        fontSize: 10, color: "var(--text-muted)",
        pointerEvents: "none",
      }}>
        {result.gated && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 3, color: "var(--warning)" }}>
            <Lock size={10} /> Gated
          </span>
        )}
      </div>
    </div>
  );
}

function BackendToggle({ value, onChange }: { value: BackendFilter; onChange: (v: BackendFilter) => void }) {
  const opts: BackendFilter[] = ["all", "mlx", "hf"];
  return (
    <div style={{ display: "flex", background: "var(--bg-secondary)", border: "1px solid var(--border-default)", borderRadius: 6, overflow: "hidden" }}>
      {opts.map((o) => (
        <button
          key={o}
          onClick={() => onChange(o)}
          style={{
            padding: "6px 10px",
            background: value === o ? "var(--bg-elevated)" : "transparent",
            border: "none",
            color: value === o ? "var(--text-primary)" : "var(--text-tertiary)",
            fontSize: 11,
            fontWeight: value === o ? 500 : 400,
            cursor: "pointer",
            textTransform: "uppercase",
            letterSpacing: "0.02em",
          }}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

// ── Disclosure ─────────────────────────────────────────────────────────

function HubDisclosure({ onAccept, onCancel }: { onAccept: () => void; onCancel: () => void }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef(onCancel);

  useEffect(() => {
    cancelRef.current = onCancel;
  }, [onCancel]);

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null;
    const frame = window.requestAnimationFrame(() => {
      const firstButton = dialogRef.current?.querySelector<HTMLElement>("button");
      (firstButton ?? dialogRef.current)?.focus();
    });
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        cancelRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )).filter((element) => element.getClientRects().length > 0);
      if (focusable.length === 0) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || !dialogRef.current.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", handler);
      previousFocus?.focus();
    };
  }, []);

  return (
    <>
      <div onClick={onCancel} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 110 }} />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="hub-disclosure-title"
        tabIndex={-1}
        style={{
        position: "fixed",
        top: "50%", left: "50%", transform: "translate(-50%, -50%)",
        width: 440,
        background: "var(--bg-primary)",
        border: "1px solid var(--border-default)",
        borderRadius: 10,
        padding: 24,
        zIndex: 120,
        boxShadow: "0 20px 50px rgba(0,0,0,0.5)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <Globe size={16} style={{ color: "var(--accent)" }} />
          <h3 id="hub-disclosure-title" style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "var(--text-primary)" }}>
            Enable HuggingFace search?
          </h3>
        </div>
        <p style={{ margin: "0 0 16px", fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.6 }}>
          Searching the Hub sends your queries to <code style={{ background: "var(--bg-elevated)", padding: "1px 5px", borderRadius: 3, fontSize: 11 }}>huggingface.co</code>.
          No personal data is included — just your search terms. Results are cached briefly to reduce load.
        </p>
        <p style={{ margin: "0 0 20px", fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.6 }}>
          For gated models you'll need an HF token (set in Settings).
        </p>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button onClick={onCancel} style={{
            padding: "6px 14px", background: "transparent", border: "1px solid var(--border-default)",
            borderRadius: 6, color: "var(--text-secondary)", fontSize: 12, cursor: "pointer",
          }}>Cancel</button>
          <button onClick={onAccept} style={{
            padding: "6px 14px", background: "var(--accent)", border: "none",
            borderRadius: 6, color: "white", fontSize: 12, fontWeight: 500, cursor: "pointer",
          }}>Enable</button>
        </div>
      </div>
    </>
  );
}

// ── Small helpers ──────────────────────────────────────────────────────

function TabButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "10px 2px",
        marginRight: 20,
        background: "none",
        border: "none",
        borderBottom: `2px solid ${active ? "var(--accent)" : "transparent"}`,
        color: active ? "var(--text-primary)" : "var(--text-tertiary)",
        fontSize: 13,
        fontWeight: active ? 500 : 400,
        cursor: "pointer",
        transition: "color 120ms ease-out, border-color 120ms ease-out",
      }}
    >
      {label}
    </button>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: 32 }}>
      <h2 className="section-heading">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "minmax(0, 1fr)",
      gap: 0,
    }}>
      {children}
    </div>
  );
}

function SkeletonGrid({ count }: { count: number }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 8 }}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          style={{
            height: 92,
            borderRadius: 3,
            border: "1px solid var(--border-default)",
            background: "var(--bg-secondary)",
            opacity: 0.5,
          }}
        />
      ))}
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div style={{
      display: "flex", alignItems: "flex-start", gap: 10,
      padding: "12px 16px",
      background: "var(--error-muted)",
      border: "1px solid rgba(229,83,75,0.3)",
      borderRadius: 8,
      marginBottom: 20,
    }}>
      <AlertCircle size={14} style={{ color: "var(--error)", flexShrink: 0, marginTop: 2 }} />
      <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
        {message}
      </div>
    </div>
  );
}
