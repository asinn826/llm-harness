/**
 * ModelsView — full-page model browse/discover/download experience.
 *
 * PR 1: Library tab only. Shows Recommended (starred) + cached cards.
 * PR 2 will add the Hub tab.
 */

import { useEffect, useMemo, useState } from "react";
import { Package } from "lucide-react";
import { models as modelsApi } from "../lib/api";
import type { ModelInfo } from "../lib/types";
import { ModelCard } from "../components/ModelCard";
import { useDownloads } from "../contexts/DownloadsContext";

type Tab = "library";

export function ModelsView() {
  const [tab, _setTab] = useState<Tab>("library");
  const [recommended, setRecommended] = useState<ModelInfo[]>([]);
  const [cached, setCached] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const { subscribe } = useDownloads();

  const refresh = async () => {
    try {
      const data = await modelsApi.list();
      setRecommended(data.recommended);
      setCached(data.cached);
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  // Refetch whenever a download completes (picks up newly-cached models)
  useEffect(() => {
    return subscribe((event) => {
      if (event.type === "completed") refresh();
    });
  }, [subscribe]);

  // Sort recommended: active first, then cached, then uncached. Stable within groups.
  const recommendedSorted = useMemo(() => {
    return [...recommended].sort((a, b) => {
      const aScore = (a.is_loaded ? 2 : 0) + (a.is_cached ? 1 : 0);
      const bScore = (b.is_loaded ? 2 : 0) + (b.is_cached ? 1 : 0);
      return bScore - aScore;
    });
  }, [recommended]);

  // Cached-only (not already in recommended) sorted by last_used desc
  const cachedSorted = useMemo(() => {
    return [...cached].sort((a, b) => (b.last_used ?? 0) - (a.last_used ?? 0));
  }, [cached]);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "hidden" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          padding: "16px 32px",
          borderBottom: "1px solid var(--border-subtle)",
          flexShrink: 0,
          gap: 12,
        }}
      >
        <Package size={16} style={{ color: "var(--text-tertiary)" }} />
        <h1 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: "var(--text-primary)", letterSpacing: "-0.01em" }}>
          Models
        </h1>
      </div>

      {/* Tabs (single tab in PR 1; structure in place for PR 2) */}
      <div
        style={{
          display: "flex",
          padding: "0 32px",
          borderBottom: "1px solid var(--border-subtle)",
          flexShrink: 0,
          gap: 4,
        }}
      >
        <TabButton active={tab === "library"} onClick={() => {}} label="Library" />
        {/* PR 2 will add: <TabButton label="Hub" ... /> */}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 32px" }}>
          {loading && <LoadingSkeleton />}

          {!loading && (
            <>
              {/* Recommended section */}
              {recommendedSorted.length > 0 && (
                <Section title="Recommended">
                  <Grid>
                    {recommendedSorted.map((m) => (
                      <ModelCard key={m.id} model={m} starred />
                    ))}
                  </Grid>
                </Section>
              )}

              {/* Cached-only section */}
              {cachedSorted.length > 0 && (
                <Section title={`Downloaded (${cachedSorted.length})`}>
                  <Grid>
                    {cachedSorted.map((m) => (
                      <ModelCard key={m.id} model={m} />
                    ))}
                  </Grid>
                </Section>
              )}

              {/* Empty state */}
              {recommendedSorted.length === 0 && cachedSorted.length === 0 && (
                <div style={{ padding: "48px 0", textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
                  No models available.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Local components ────────────────────────────────────────────────────

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
      <h2
        style={{
          fontSize: 11,
          fontWeight: 500,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          margin: "0 0 14px",
        }}
      >
        {title}
      </h2>
      {children}
    </section>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
        gap: 12,
      }}
    >
      {children}
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 12 }}>
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            height: 160,
            borderRadius: 10,
            border: "1px solid var(--border-subtle)",
            background: "var(--bg-secondary)",
            opacity: 0.5,
          }}
        />
      ))}
    </div>
  );
}
