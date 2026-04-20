import { useState, useEffect, type ReactNode } from "react";
import {
  MessageSquare,
  Columns2,
  Clock,
  Settings,
  Plus,
  PanelLeftClose,
  PanelLeft,
} from "lucide-react";
import { sessions as sessionsApi } from "../lib/api";
import type { Session } from "../lib/types";
import { getModelColor } from "../lib/types";

type View = "chat" | "compare" | "sessions" | "settings";

interface SidebarProps {
  currentView: View;
  onViewChange: (view: View) => void;
  activeSessionId: string | null;
  onSessionSelect: (id: string) => void;
  onNewSession: () => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  modelSwitcher?: ReactNode;
  /** Bump to trigger session list refresh */
  refreshKey?: number;
}

const NAV_ITEMS: { view: View; icon: typeof MessageSquare; label: string }[] = [
  { view: "chat", icon: MessageSquare, label: "Chat" },
  { view: "compare", icon: Columns2, label: "Compare" },
  { view: "sessions", icon: Clock, label: "History" },
];

export function Sidebar({
  currentView,
  onViewChange,
  activeSessionId,
  onSessionSelect,
  onNewSession,
  collapsed,
  onToggleCollapse,
  modelSwitcher,
  refreshKey,
}: SidebarProps) {
  const [recentSessions, setRecentSessions] = useState<Session[]>([]);

  useEffect(() => {
    sessionsApi.list(20).then(setRecentSessions).catch(() => {});
  }, [activeSessionId, refreshKey]);

  return (
    <div
      style={{
        width: collapsed ? 48 : 240,
        transition: "width 200ms ease-out",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        background: "var(--bg-secondary)",
        borderRight: "1px solid var(--border-subtle)",
        flexShrink: 0,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: collapsed ? "center" : "space-between",
          padding: collapsed ? "12px 0" : "12px",
          borderBottom: "1px solid var(--border-subtle)",
          flexShrink: 0,
          minHeight: 48,
        }}
      >
        {!collapsed && (
          <span style={{ color: "var(--text-primary)", fontWeight: 600, fontSize: 14, letterSpacing: "-0.02em" }}>
            Harness
          </span>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
          <button
            onClick={onNewSession}
            className="flex items-center justify-center rounded-md text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
            style={{ width: 28, height: 28 }}
            title="New session"
          >
            <Plus size={16} strokeWidth={1.5} />
          </button>
          <button
            onClick={onToggleCollapse}
            className="flex items-center justify-center rounded-md text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
            style={{ width: 28, height: 28 }}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <PanelLeft size={16} strokeWidth={1.5} /> : <PanelLeftClose size={16} strokeWidth={1.5} />}
          </button>
        </div>
      </div>

      {/* Model switcher */}
      {modelSwitcher && <div style={{ flexShrink: 0 }}>{modelSwitcher}</div>}

      {/* Navigation */}
      <div
        style={{
          display: "flex",
          flexDirection: collapsed ? "column" : "row",
          gap: 2,
          padding: collapsed ? "8px 4px" : "8px",
          borderBottom: "1px solid var(--border-subtle)",
          flexShrink: 0,
        }}
      >
        {NAV_ITEMS.map(({ view, icon: Icon, label }) => (
          <button
            key={view}
            onClick={() => onViewChange(view)}
            className={`
              flex items-center justify-center rounded-md
              transition-colors duration-[var(--duration-fast)]
              ${currentView === view
                ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)]"}
            `}
            style={{
              flex: collapsed ? "none" : 1,
              gap: 6,
              padding: collapsed ? "8px" : "6px",
              fontSize: 12,
              width: collapsed ? 40 : undefined,
              height: collapsed ? 36 : undefined,
            }}
            title={label}
          >
            <Icon size={14} strokeWidth={1.5} />
            {!collapsed && <span>{label}</span>}
          </button>
        ))}
      </div>

      {/* Session list (hidden when collapsed) */}
      <div
        style={{
          flex: 1,
          overflowY: collapsed ? "hidden" : "auto",
          overflowX: "hidden",
          padding: collapsed ? 0 : "8px",
          opacity: collapsed ? 0 : 1,
          transition: "opacity 150ms ease-out",
        }}
      >
        {recentSessions.length === 0 && (
          <div style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", paddingTop: 32 }}>
            No sessions yet
          </div>
        )}
        {recentSessions.map((session) => (
          <button
            key={session.id}
            onClick={() => onSessionSelect(session.id)}
            className={`
              w-full text-left rounded-md mb-0.5
              transition-colors duration-[var(--duration-fast)]
              ${activeSessionId === session.id
                ? "bg-[var(--bg-elevated)] border-l-2 border-[var(--accent)]"
                : "hover:bg-[var(--bg-surface)]"}
            `}
            style={{ padding: "8px 10px" }}
          >
            <div style={{ fontSize: 12, color: "var(--text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {session.title}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 2 }}>
              {session.models?.map((model) => (
                <div
                  key={model}
                  style={{ width: 6, height: 6, borderRadius: "50%", background: getModelColor(model) }}
                />
              ))}
              <span style={{ fontSize: 10, color: "var(--text-muted)", lineHeight: 1 }}>
                {formatRelativeTime(session.updated_at)}
              </span>
            </div>
          </button>
        ))}
      </div>

      {/* Settings */}
      <div style={{ padding: collapsed ? "8px 4px" : "8px", borderTop: "1px solid var(--border-subtle)", flexShrink: 0 }}>
        <button
          onClick={() => onViewChange("settings")}
          className={`
            w-full flex items-center rounded-md
            transition-colors duration-[var(--duration-fast)]
            ${currentView === "settings"
              ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
              : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)]"}
          `}
          style={{
            gap: 8,
            padding: collapsed ? "8px" : "8px 10px",
            fontSize: 12,
            justifyContent: collapsed ? "center" : "flex-start",
          }}
        >
          <Settings size={14} strokeWidth={1.5} />
          {!collapsed && "Settings"}
        </button>
      </div>
    </div>
  );
}

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDays = Math.floor(diffHr / 24);
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
