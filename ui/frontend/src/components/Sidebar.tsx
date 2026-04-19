import { useState, useEffect, type ReactNode } from "react";
import {
  MessageSquare,
  Columns2,
  Package,
  Clock,
  Settings,
  Plus,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { sessions as sessionsApi } from "../lib/api";
import type { Session } from "../lib/types";
import { getModelColor } from "../lib/types";

type View = "chat" | "compare" | "models" | "sessions" | "settings";

interface SidebarProps {
  currentView: View;
  onViewChange: (view: View) => void;
  activeSessionId: string | null;
  onSessionSelect: (id: string) => void;
  onNewSession: () => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  /** Slot for the model switcher, rendered below the header */
  modelSwitcher?: ReactNode;
}

const NAV_ITEMS: { view: View; icon: typeof MessageSquare; label: string }[] = [
  { view: "chat", icon: MessageSquare, label: "Chat" },
  { view: "compare", icon: Columns2, label: "Compare" },
  { view: "models", icon: Package, label: "Models" },
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
}: SidebarProps) {
  const [recentSessions, setRecentSessions] = useState<Session[]>([]);

  useEffect(() => {
    sessionsApi.list(20).then(setRecentSessions).catch(() => {});
  }, [activeSessionId]);

  if (collapsed) {
    return (
      <div className="flex flex-col items-center w-12 bg-[var(--bg-secondary)] border-r border-[var(--border-subtle)] py-3 gap-1 shrink-0">
        {NAV_ITEMS.map(({ view, icon: Icon }) => (
          <button
            key={view}
            onClick={() => onViewChange(view)}
            className={`
              w-9 h-9 flex items-center justify-center rounded-md
              transition-colors duration-[var(--duration-fast)]
              ${currentView === view
                ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)]"}
            `}
            title={view.charAt(0).toUpperCase() + view.slice(1)}
          >
            <Icon size={18} strokeWidth={1.5} />
          </button>
        ))}

        <div className="flex-1" />

        <button
          onClick={onToggleCollapse}
          className="w-9 h-9 flex items-center justify-center rounded-md text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
          title="Expand sidebar"
        >
          <ChevronRight size={16} strokeWidth={1.5} />
        </button>

        <button
          onClick={() => onViewChange("settings")}
          className={`
            w-9 h-9 flex items-center justify-center rounded-md
            transition-colors duration-[var(--duration-fast)]
            ${currentView === "settings"
              ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
              : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)]"}
          `}
          title="Settings"
        >
          <Settings size={18} strokeWidth={1.5} />
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col w-60 h-screen bg-[var(--bg-secondary)] border-r border-[var(--border-subtle)] shrink-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-[var(--border-subtle)] shrink-0">
        <span className="text-[var(--text-primary)] font-semibold text-sm tracking-tight">
          Harness
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={onNewSession}
            className="w-7 h-7 flex items-center justify-center rounded-md text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
            title="New session"
          >
            <Plus size={16} strokeWidth={1.5} />
          </button>
          <button
            onClick={onToggleCollapse}
            className="w-7 h-7 flex items-center justify-center rounded-md text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
            title="Collapse sidebar"
          >
            <ChevronLeft size={16} strokeWidth={1.5} />
          </button>
        </div>
      </div>

      {/* Model switcher */}
      {modelSwitcher && <div className="shrink-0">{modelSwitcher}</div>}

      {/* Navigation */}
      <div className="flex gap-0.5 px-2 py-2 border-b border-[var(--border-subtle)] shrink-0">
        {NAV_ITEMS.map(({ view, icon: Icon, label }) => (
          <button
            key={view}
            onClick={() => onViewChange(view)}
            className={`
              flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-xs
              transition-colors duration-[var(--duration-fast)]
              ${currentView === view
                ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)]"}
            `}
          >
            <Icon size={14} strokeWidth={1.5} />
            <span>{label}</span>
          </button>
        ))}
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {recentSessions.length === 0 && (
          <div className="text-[var(--text-muted)] text-xs text-center py-8">
            No sessions yet
          </div>
        )}
        {recentSessions.map((session) => (
          <button
            key={session.id}
            onClick={() => onSessionSelect(session.id)}
            className={`
              w-full text-left px-2.5 py-2 rounded-md mb-0.5
              transition-colors duration-[var(--duration-fast)]
              ${activeSessionId === session.id
                ? "bg-[var(--bg-elevated)] border-l-2 border-[var(--accent)]"
                : "hover:bg-[var(--bg-surface)]"}
            `}
          >
            <div className="text-xs text-[var(--text-primary)] truncate leading-snug">
              {session.title}
            </div>
            <div className="flex items-center gap-1.5 mt-0.5">
              {session.models?.map((model) => (
                <div
                  key={model}
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ background: getModelColor(model) }}
                />
              ))}
              <span className="text-[10px] text-[var(--text-muted)] leading-none">
                {formatRelativeTime(session.updated_at)}
              </span>
            </div>
          </button>
        ))}
      </div>

      {/* Bottom */}
      <div className="px-2 py-2 border-t border-[var(--border-subtle)] shrink-0">
        <button
          onClick={() => onViewChange("settings")}
          className={`
            w-full flex items-center gap-2 px-2.5 py-2 rounded-md text-xs
            transition-colors duration-[var(--duration-fast)]
            ${currentView === "settings"
              ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
              : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)]"}
          `}
        >
          <Settings size={14} strokeWidth={1.5} />
          Settings
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
