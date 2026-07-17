import { useState, useEffect, type ReactNode } from "react";
import {
  AlertTriangle,
  Columns2,
  Loader2,
  Package,
  RefreshCw,
  Search,
  Settings,
  Plus,
  PanelLeftClose,
  PanelLeft,
  FolderOpen,
} from "lucide-react";
import { getErrorMessage, sessions as sessionsApi } from "../lib/api";
import type { Project, Session, SessionVisualState } from "../lib/types";
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
  projectLoadError?: string | null;
  onRetryProjects?: () => void;
  sessionStates?: Record<string, SessionVisualState>;
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
  projectLoadError,
  onRetryProjects,
  sessionStates = {},
  modelSwitcher,
  refreshKey,
}: SidebarProps) {
  const [historyByProject, setHistoryByProject] = useState<Record<string, Session[]>>({});
  const [historyLoad, setHistoryLoad] = useState<{
    projectId: string;
    status: "idle" | "loading" | "ready" | "error";
    error: string | null;
  }>({ projectId: "", status: "idle", error: null });
  const [historyRetryKey, setHistoryRetryKey] = useState(0);
  const [historyQuery, setHistoryQuery] = useState("");
  const [isCreatingProject, setIsCreatingProject] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [projectError, setProjectError] = useState<string | null>(null);
  const [projectSuccess, setProjectSuccess] = useState<string | null>(null);
  const [projectSubmitting, setProjectSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => {
      if (!active) return;
      setHistoryLoad({ projectId: activeProjectId, status: "loading", error: null });
      Promise.all([
        sessionsApi.list(50, 0, { project_id: activeProjectId, is_compare: true }),
        sessionsApi.list(15, 0, { project_id: activeProjectId, is_compare: false }),
      ])
        .then(([comparisons, chats]) => {
          if (active) {
            setHistoryByProject((current) => ({
              ...current,
              [activeProjectId]: [...comparisons, ...chats],
            }));
            setHistoryLoad({ projectId: activeProjectId, status: "ready", error: null });
          }
        })
        .catch((error) => {
          if (active) {
            setHistoryLoad({
              projectId: activeProjectId,
              status: "error",
              error: getErrorMessage(error, "Couldn’t load comparison history."),
            });
          }
        });
    }, 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [activeProjectId, activeSessionId, refreshKey, historyRetryKey]);

  const recentSessions = historyByProject[activeProjectId] ?? [];
  const normalizedQuery = historyQuery.trim().toLowerCase();
  const visibleSessions = normalizedQuery
    ? recentSessions.filter((session) =>
        session.title.toLowerCase().includes(normalizedQuery) ||
        session.models.some((model) => model.toLowerCase().includes(normalizedQuery))
      )
    : recentSessions;

  const cancelProjectCreation = () => {
    setIsCreatingProject(false);
    setProjectName("");
    setProjectError(null);
  };

  const submitProject = async () => {
    const name = projectName.trim();
    if (!name) return;
    if (name.length > 80) {
      setProjectError("Project names must be 80 characters or fewer.");
      return;
    }
    if (projects.some((project) => project.name.toLowerCase() === name.toLowerCase())) {
      setProjectError("A project with this name already exists.");
      return;
    }
    setProjectError(null);
    setProjectSubmitting(true);
    try {
      await onProjectCreate(name);
      setProjectName("");
      setIsCreatingProject(false);
      setProjectSuccess(`Created ${name}.`);
      window.setTimeout(() => setProjectSuccess(null), 3000);
    } catch (error) {
      setProjectError(getErrorMessage(error, "Couldn’t create this project."));
    } finally {
      setProjectSubmitting(false);
    }
  };

  const comparisons = visibleSessions.filter((session) => Boolean(session.is_compare));
  const chats = visibleSessions.filter((session) => !session.is_compare);

  return (
    <aside
      className="app-sidebar"
      aria-label="Harness navigation"
      style={{
        width: collapsed ? 48 : 240,
        transition: "width 200ms ease-out",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        flexShrink: 0,
        overflow: collapsed ? "visible" : "hidden",
      }}
    >
      {/* Header */}
      <header
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
              type="button"
              onClick={onNewSession}
              className="icon-tooltip flex items-center justify-center rounded-md text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
              data-tooltip="New comparison"
              style={{ width: 28, height: 28 }}
              title="New comparison"
              aria-label="New comparison"
            >
              <Plus size={16} strokeWidth={1.5} />
            </button>
          )}
          <button
            type="button"
            onClick={onToggleCollapse}
            className="icon-tooltip flex items-center justify-center rounded-md text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
            data-tooltip={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            style={{ width: 28, height: 28 }}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <PanelLeft size={16} strokeWidth={1.5} /> : <PanelLeftClose size={16} strokeWidth={1.5} />}
          </button>
        </div>
      </header>

      {!collapsed && (
        <div style={{ padding: "10px 12px 4px" }}>
          <button type="button" className="sidebar-new" onClick={onNewSession}>
            <Plus size={15} strokeWidth={1.8} />
            New comparison
          </button>
        </div>
      )}

      {/* Project scope */}
      {!collapsed && (
        <div className="border-b border-[var(--border-subtle)] px-3 pb-3 pt-4">
          <div className="sidebar-kicker mb-2 px-0.5">Project</div>
          <div className="flex items-center gap-1.5">
            <FolderOpen size={13} className="ml-1 text-[var(--text-muted)]" />
            <select
              value={activeProjectId}
              onChange={(event) => onProjectChange(event.target.value)}
              className="min-w-0 flex-1 rounded-md bg-[var(--bg-surface)] px-2 py-1.5 text-sm text-[var(--text-secondary)] outline-none border border-transparent focus:border-[var(--border-default)]"
              aria-label="Active project"
            >
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => {
                if (isCreatingProject) cancelProjectCreation();
                else {
                  setProjectSuccess(null);
                  setIsCreatingProject(true);
                }
              }}
              className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--text-muted)] hover:bg-[var(--bg-surface)] hover:text-[var(--text-secondary)]"
              data-tooltip="Create project"
              title="Create project"
              aria-label="Create project"
              aria-expanded={isCreatingProject}
            >
              <Plus size={14} />
            </button>
          </div>
          {projectLoadError && (
            <div className="sidebar-inline-status" role="alert">
              <span>Project list unavailable</span>
              {onRetryProjects && (
                <button type="button" onClick={onRetryProjects} aria-label="Retry loading projects">
                  <RefreshCw size={12} aria-hidden="true" /> Retry
                </button>
              )}
            </div>
          )}
          {projectSuccess && <div className="sidebar-inline-success" role="status">{projectSuccess}</div>}
          {isCreatingProject && (
            <form className="project-create-form" onSubmit={(event) => { event.preventDefault(); void submitProject(); }}>
              <label htmlFor="project-name" className="sr-only">Project name</label>
              <input
                id="project-name"
                autoFocus
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") cancelProjectCreation();
                }}
                placeholder="Project name"
                className="min-w-0 flex-1 rounded-md border border-[var(--border-default)] bg-[var(--bg-primary)] px-2 py-1.5 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
                maxLength={80}
                aria-invalid={Boolean(projectError)}
                aria-describedby={projectError ? "project-create-error" : undefined}
              />
              <div className="project-create-actions">
                <button type="button" onClick={cancelProjectCreation}>Cancel</button>
                <button
                  type="submit"
                  className="rounded-md bg-[var(--accent)] px-2 text-sm text-white disabled:opacity-40"
                  disabled={!projectName.trim() || projectSubmitting}
                >
                  {projectSubmitting ? "Creating…" : "Create"}
                </button>
              </div>
              {projectError && (
                <div id="project-create-error" className="mt-1 text-xs text-[var(--error)]" role="alert">{projectError}</div>
              )}
            </form>
          )}
        </div>
      )}

      {/* Model switcher */}
      {modelSwitcher && <div style={{ flexShrink: 0 }}>{modelSwitcher}</div>}

      {/* Navigation */}
      <nav
        className="sidebar-nav"
        aria-label="Primary"
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
            type="button"
            key={view}
            onClick={() => onViewChange(view)}
            className={`
              ${collapsed ? "icon-tooltip" : ""}
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
              fontSize: 14,
              width: collapsed ? 40 : "100%",
              height: collapsed ? 36 : 34,
              justifyContent: collapsed ? "center" : "flex-start",
            }}
            title={label}
            data-tooltip={label}
            aria-label={label}
            aria-current={currentView === view ? "page" : undefined}
          >
            <Icon size={14} strokeWidth={1.5} />
            {!collapsed && <span>{label}</span>}
          </button>
        ))}
      </nav>

      {/* Session list (hidden when collapsed) */}
      {!collapsed && (
        <div
          className="sidebar-history"
          style={{
            flex: 1,
            overflowY: "auto",
            overflowX: "hidden",
            padding: "8px",
          }}
        >
        {recentSessions.length > 5 && (
          <div className="sidebar-search">
            <Search size={13} aria-hidden="true" />
            <label className="sr-only" htmlFor="history-search">Search history</label>
            <input
              id="history-search"
              value={historyQuery}
              onChange={(event) => setHistoryQuery(event.target.value)}
              placeholder="Search history"
            />
          </div>
        )}
        {historyLoad.projectId === activeProjectId && historyLoad.status === "error" && (
          <div className="sidebar-history-status" role="alert" title={historyLoad.error ?? undefined}>
            <AlertTriangle size={13} aria-hidden="true" />
            <span>{recentSessions.length > 0 ? "Offline · showing saved history" : "History unavailable"}</span>
            <button type="button" onClick={() => setHistoryRetryKey((key) => key + 1)}>Retry</button>
          </div>
        )}
        {historyLoad.projectId === activeProjectId && historyLoad.status === "loading" && recentSessions.length === 0 && (
          <div className="sidebar-empty" role="status"><Loader2 size={14} className="animate-spin" /> Loading history…</div>
        )}
        {historyLoad.projectId === activeProjectId && historyLoad.status === "ready" && recentSessions.length === 0 && (
          <div style={{ color: "var(--text-muted)", fontSize: 14, textAlign: "center", paddingTop: 32 }}>
            No comparisons yet
          </div>
        )}
        {recentSessions.length > 0 && visibleSessions.length === 0 && (
          <div className="sidebar-empty">No matching history</div>
        )}
        <SessionGroup
          label="Comparisons"
          sessions={comparisons}
          activeSessionId={activeSessionId}
          onSelect={onSessionSelect}
          sessionStates={sessionStates}
        />
        <SessionGroup
          label="Chats"
          sessions={chats}
          activeSessionId={activeSessionId}
          onSelect={onSessionSelect}
          sessionStates={sessionStates}
        />
        </div>
      )}

      {/* Settings */}
      <div className="sidebar-settings" style={{ padding: collapsed ? "8px 4px" : "8px", borderTop: "1px solid var(--border-subtle)", flexShrink: 0 }}>
        <button
          type="button"
          onClick={() => onViewChange("settings")}
          className={`
            ${collapsed ? "icon-tooltip" : ""}
            w-full flex items-center rounded-md
            transition-colors duration-[var(--duration-fast)]
            ${currentView === "settings"
              ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
              : "text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)]"}
          `}
          style={{
            gap: 8,
            padding: collapsed ? "8px" : "8px 10px",
            fontSize: 14,
            justifyContent: collapsed ? "center" : "flex-start",
          }}
          title="Settings"
          data-tooltip="Settings"
          aria-label="Settings"
          aria-current={currentView === "settings" ? "page" : undefined}
        >
          <Settings size={14} strokeWidth={1.5} />
          {!collapsed && "Settings"}
        </button>
      </div>
    </aside>
  );
}

function SessionGroup({
  label,
  sessions,
  activeSessionId,
  onSelect,
  sessionStates,
}: {
  label: string;
  sessions: Session[];
  activeSessionId: string | null;
  onSelect: (session: Session) => void;
  sessionStates: Record<string, SessionVisualState>;
}) {
  if (sessions.length === 0) return null;

  return (
    <div className="mb-3">
      <div className="sidebar-kicker px-2 pb-2 pt-2">
        {label}
      </div>
      {sessions.map((session) => {
        const visualState = sessionStates[session.id];
        const modelSummary = summarizeModels(session.models);
        return (
          <button
            key={session.id}
            type="button"
            onClick={() => onSelect(session)}
            className={`
              session-row w-full text-left rounded-md mb-0.5
              transition-colors duration-[var(--duration-fast)]
              ${activeSessionId === session.id
                ? "bg-[var(--bg-elevated)] border-l-2 border-[var(--accent)]"
                : "hover:bg-[var(--bg-surface)]"}
            `}
            style={{ padding: "8px 10px" }}
            aria-current={activeSessionId === session.id ? "page" : undefined}
            data-session-state={visualState ?? "idle"}
            title={`${session.title} — ${session.models.join(", ") || "No model recorded"}`}
          >
            <div style={{ fontSize: 14, color: "var(--text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {session.title}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3 }}>
              <span className="session-model-markers" aria-hidden="true">
                {session.models.slice(0, 3).map((model) => (
                  <span key={model} style={{ background: getModelColor(model) }} />
                ))}
              </span>
              <span className="session-meta">
                <span className="session-model-copy">{modelSummary || "No model recorded"}</span>
                <span className="session-meta-spacer" aria-hidden="true" />
                {visualState && (
                  <span className="session-state-label">
                    {visualState === "running" && "Running…"}
                    {visualState === "failed" && "Needs attention"}
                    {visualState === "unread" && "New result"}
                  </span>
                )}
                <time dateTime={session.updated_at}>{formatRelativeTime(session.updated_at)}</time>
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function summarizeModels(models: string[]): string {
  if (models.length === 0) return "";
  const first = models[0].split("/").pop() || models[0];
  return models.length > 1 ? `${first} +${models.length - 1}` : first;
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
