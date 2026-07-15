import { useState, useEffect, type ReactNode } from "react";
import {
  Columns2,
  Package,
  Settings,
  Plus,
  PanelLeftClose,
  PanelLeft,
  FolderOpen,
} from "lucide-react";
import { sessions as sessionsApi } from "../lib/api";
import type { Project, Session } from "../lib/types";
import { getModelColor } from "../lib/types";

type View = "chat" | "compare" | "models" | "settings";

interface SidebarProps {
  currentView: View;
  onViewChange: (view: View) => void;
  activeSessionId: string | null;
  onSessionSelect: (session: Session) => void;
  onNewSession: () => void;
  projects: Project[];
  activeProjectId: string;
  onProjectChange: (projectId: string) => void;
  onProjectCreate: (name: string) => Promise<Project>;
  collapsed: boolean;
  onToggleCollapse: () => void;
  modelSwitcher?: ReactNode;
  /** Bump to trigger session list refresh */
  refreshKey?: number;
}

const NAV_ITEMS: { view: View; icon: typeof Columns2; label: string }[] = [
  { view: "compare", icon: Columns2, label: "Compare" },
  { view: "models", icon: Package, label: "Models" },
];

export function Sidebar({
  currentView,
  onViewChange,
  activeSessionId,
  onSessionSelect,
  onNewSession,
  projects,
  activeProjectId,
  onProjectChange,
  onProjectCreate,
  collapsed,
  onToggleCollapse,
  modelSwitcher,
  refreshKey,
}: SidebarProps) {
  const [sessionHistory, setSessionHistory] = useState<{
    projectId: string;
    sessions: Session[];
  }>({ projectId: "", sessions: [] });
  const [isCreatingProject, setIsCreatingProject] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [projectError, setProjectError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      sessionsApi.list(50, 0, { project_id: activeProjectId, is_compare: true }),
      sessionsApi.list(15, 0, { project_id: activeProjectId, is_compare: false }),
    ])
      .then(([comparisons, chats]) => {
        if (active) {
          setSessionHistory({
            projectId: activeProjectId,
            sessions: [...comparisons, ...chats],
          });
        }
      })
      .catch(() => {
        if (active) setSessionHistory({ projectId: activeProjectId, sessions: [] });
      });
    return () => {
      active = false;
    };
  }, [activeProjectId, activeSessionId, refreshKey]);

  const recentSessions = sessionHistory.projectId === activeProjectId
    ? sessionHistory.sessions
    : [];

  const submitProject = async () => {
    const name = projectName.trim();
    if (!name) return;
    setProjectError(null);
    try {
      await onProjectCreate(name);
      setProjectName("");
      setIsCreatingProject(false);
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "Could not create project");
    }
  };

  const comparisons = recentSessions.filter((session) => Boolean(session.is_compare));
  const chats = recentSessions.filter((session) => !session.is_compare);

  return (
    <div
      className="app-sidebar"
      style={{
        width: collapsed ? 48 : 240,
        transition: "width 200ms ease-out",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        flexShrink: 0,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        className="sidebar-header"
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
          <div className="brand-lockup">
            <strong className="brand-name">Harness</strong>
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
          {collapsed && (
            <button
              onClick={onNewSession}
              className="flex items-center justify-center rounded-md text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
              style={{ width: 28, height: 28 }}
              title="New comparison"
            >
              <Plus size={16} strokeWidth={1.5} />
            </button>
          )}
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

      {!collapsed && (
        <div style={{ padding: "10px 12px 4px" }}>
          <button className="sidebar-new" onClick={onNewSession}>
            <Plus size={15} strokeWidth={1.8} />
            New comparison
          </button>
        </div>
      )}

      {/* Project scope */}
      {!collapsed && (
        <div className="border-b border-[var(--border-subtle)] px-3 pb-3 pt-4">
          <div className="sidebar-kicker mb-2 px-0.5">Workspace</div>
          <div className="flex items-center gap-1.5">
            <FolderOpen size={13} className="ml-1 text-[var(--text-muted)]" />
            <select
              value={activeProjectId}
              onChange={(event) => onProjectChange(event.target.value)}
              className="min-w-0 flex-1 rounded-md bg-[var(--bg-surface)] px-2 py-1.5 text-xs text-[var(--text-secondary)] outline-none border border-transparent focus:border-[var(--border-default)]"
              aria-label="Active project"
            >
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
            <button
              onClick={() => setIsCreatingProject((current) => !current)}
              className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--text-muted)] hover:bg-[var(--bg-surface)] hover:text-[var(--text-secondary)]"
              title="Create project"
            >
              <Plus size={14} />
            </button>
          </div>
          {isCreatingProject && (
            <div className="mt-2">
              <div className="flex gap-1.5">
                <input
                  autoFocus
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void submitProject();
                    if (event.key === "Escape") setIsCreatingProject(false);
                  }}
                  placeholder="Project name"
                  className="min-w-0 flex-1 rounded-md border border-[var(--border-default)] bg-[var(--bg-primary)] px-2 py-1.5 text-xs text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
                />
                <button
                  onClick={() => void submitProject()}
                  className="rounded-md bg-[var(--accent)] px-2 text-xs text-white disabled:opacity-40"
                  disabled={!projectName.trim()}
                >
                  Add
                </button>
              </div>
              {projectError && (
                <div className="mt-1 text-[10px] text-[var(--error)]">{projectError}</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Model switcher */}
      {modelSwitcher && <div style={{ flexShrink: 0 }}>{modelSwitcher}</div>}

      {/* Navigation */}
      <div
        className="sidebar-nav"
        style={{
          display: "flex",
          flexDirection: "column",
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
              flex: "none",
              gap: 6,
              padding: collapsed ? "8px" : "7px 10px",
              fontSize: 12,
              width: collapsed ? 40 : "100%",
              height: collapsed ? 36 : 34,
              justifyContent: collapsed ? "center" : "flex-start",
            }}
            title={label}
            aria-current={currentView === view ? "page" : undefined}
          >
            <Icon size={14} strokeWidth={1.5} />
            {!collapsed && <span>{label}</span>}
          </button>
        ))}
      </div>

      {/* Session list (hidden when collapsed) */}
      <div
        className="sidebar-history"
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
            No comparisons yet
          </div>
        )}
        <SessionGroup
          label="Comparisons"
          sessions={comparisons}
          activeSessionId={activeSessionId}
          onSelect={onSessionSelect}
        />
        <SessionGroup
          label="Legacy chats"
          sessions={chats}
          activeSessionId={activeSessionId}
          onSelect={onSessionSelect}
        />
      </div>

      {/* Settings */}
      <div className="sidebar-settings" style={{ padding: collapsed ? "8px 4px" : "8px", borderTop: "1px solid var(--border-subtle)", flexShrink: 0 }}>
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

function SessionGroup({
  label,
  sessions,
  activeSessionId,
  onSelect,
}: {
  label: string;
  sessions: Session[];
  activeSessionId: string | null;
  onSelect: (session: Session) => void;
}) {
  if (sessions.length === 0) return null;

  return (
    <div className="mb-3">
      <div className="sidebar-kicker px-2 pb-2 pt-2">
        {label}
      </div>
      {sessions.map((session) => (
        <button
          key={session.id}
          onClick={() => onSelect(session)}
          className={`
            session-row w-full text-left rounded-md mb-0.5
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
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3 }}>
            {session.models.map((model) => (
              <div
                key={model}
                title={model}
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
