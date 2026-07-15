import { useState, useCallback, useEffect } from "react";
import { DownloadsProvider, useDownloads } from "./contexts/DownloadsContext";
import { Sidebar } from "./components/Sidebar";
import { ModelSwitcher } from "./components/ModelSwitcher";
import { PermissionsBanner } from "./components/PermissionsBanner";
import { ChatView } from "./views/ChatView";
import { CompareView } from "./views/CompareView";
import { ModelsView } from "./views/ModelsView";
import { SettingsView } from "./views/SettingsView";
import { projects as projectsApi } from "./lib/api";
import type { ComparisonModelInput, Project, Session } from "./lib/types";

type View = "chat" | "compare" | "models" | "settings";
const ACTIVE_PROJECT_KEY = "llm-harness.active-project";

export default function App() {
  return (
    <DownloadsProvider>
      <AppInner />
    </DownloadsProvider>
  );
}

function AppInner() {
  const { currentModelId } = useDownloads();

  const [currentView, setCurrentView] = useState<View>("compare");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [activeSessionKind, setActiveSessionKind] = useState<"chat" | "compare" | null>("compare");
  const [comparisonSurfaceKey, setComparisonSurfaceKey] = useState(0);
  const [draftLineup, setDraftLineup] = useState<ComparisonModelInput[]>([]);
  const [modelBrowserMode, setModelBrowserMode] = useState<"browse" | "add-to-comparison">("browse");
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState(
    () => window.localStorage.getItem(ACTIVE_PROJECT_KEY) || "default"
  );
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sessionRefreshKey, setSessionRefreshKey] = useState(0);
  const [missingAutomation, setMissingAutomation] = useState(false);
  const [missingFullDisk, setMissingFullDisk] = useState(false);

  useEffect(() => {
    projectsApi.list().then((items) => {
      setProjects(items);
      setActiveProjectId((current) =>
        items.length > 0 && !items.some((project) => project.id === current)
          ? items[0].id
          : current
      );
    }).catch(() => {});
  }, []);

  useEffect(() => {
    window.localStorage.setItem(ACTIVE_PROJECT_KEY, activeProjectId);
  }, [activeProjectId]);

  // Check macOS permissions on startup
  useEffect(() => {
    fetch("/api/permissions")
      .then((r) => r.json())
      .then((data) => {
        setMissingAutomation(!data.messages || !data.contacts);
        setMissingFullDisk(!data.full_disk_access);
      })
      .catch(() => {});
  }, []);

  const handleNewSession = useCallback(() => {
    setActiveSessionId(null);
    setActiveSessionKind("compare");
    setDraftLineup([]);
    setComparisonSurfaceKey((key) => key + 1);
    setCurrentView("compare");
  }, []);

  const handleSessionSelect = useCallback((session: Session) => {
    setActiveSessionId(session.id);
    setDraftLineup([]);
    const kind = session.is_compare ? "compare" : "chat";
    setActiveSessionKind(kind);
    if (kind === "compare") setComparisonSurfaceKey((key) => key + 1);
    setCurrentView(kind);
  }, []);

  const handleCompareSessionCreated = useCallback((id: string) => {
    setActiveSessionId(id);
    setActiveSessionKind("compare");
    setDraftLineup([]);
    setSessionRefreshKey((k) => k + 1);
  }, []);

  const handleCompareSessionDetached = useCallback(() => {
    setActiveSessionId(null);
    setActiveSessionKind("compare");
  }, []);

  const handleChatSessionCreated = useCallback((id: string) => {
    setActiveSessionId(id);
    setActiveSessionKind("chat");
    setSessionRefreshKey((k) => k + 1);
  }, []);

  const handleComparisonComplete = useCallback(() => {
    setSessionRefreshKey((key) => key + 1);
  }, []);

  const handleProjectChange = useCallback((projectId: string) => {
    setActiveProjectId(projectId);
    setActiveSessionId(null);
    setActiveSessionKind("compare");
    setDraftLineup([]);
    setComparisonSurfaceKey((key) => key + 1);
    setCurrentView("compare");
  }, []);

  const handleProjectCreate = useCallback(async (name: string) => {
    const project = await projectsApi.create(name);
    setProjects((current) => [project, ...current]);
    handleProjectChange(project.id);
    return project;
  }, [handleProjectChange]);

  const handleTitleUpdated = useCallback(() => {
    setSessionRefreshKey((k) => k + 1);
  }, []);

  const handleViewChange = useCallback((view: View) => {
    if (view === "compare" && activeSessionKind === "chat") {
      setActiveSessionId(null);
      setActiveSessionKind("compare");
      setDraftLineup([]);
      setComparisonSurfaceKey((key) => key + 1);
    } else if (view === "chat" && activeSessionKind === "compare") {
      setActiveSessionId(null);
      setActiveSessionKind("chat");
    }
    if (view === "models") setModelBrowserMode("browse");
    setCurrentView(view);
  }, [activeSessionKind]);

  const handlePermissionsRetry = useCallback(() => {
    fetch("/api/permissions")
      .then((r) => r.json())
      .then((data) => {
        setMissingAutomation(!data.messages || !data.contacts);
        setMissingFullDisk(!data.full_disk_access);
      })
      .catch(() => {});
  }, []);

  const handleBrowseAll = useCallback(() => {
    setModelBrowserMode("browse");
    setCurrentView("models");
  }, []);

  const handleBrowseForComparison = useCallback(() => {
    setModelBrowserMode("add-to-comparison");
    setCurrentView("models");
  }, []);

  const handleAddDraftModel = useCallback((model: ComparisonModelInput) => {
    setDraftLineup((current) => {
      const existing = current.find((candidate) => candidate.model_id === model.model_id);
      if (existing) {
        return current.map((candidate) =>
          candidate.model_id === model.model_id ? { ...candidate, ...model } : candidate
        );
      }
      return current.length < 3 ? [...current, model] : current;
    });
  }, []);

  const handleRemoveDraftModel = useCallback((modelId: string) => {
    setDraftLineup((current) => current.filter((model) => model.model_id !== modelId));
  }, []);

  const handleReturnToComparison = useCallback(() => {
    setCurrentView("compare");
    setModelBrowserMode("browse");
    setComparisonSurfaceKey((key) => key + 1);
  }, []);

  return (
    <div className="app-shell" style={{ display: "flex", height: "100vh", overflow: "hidden", background: "var(--bg-primary)" }}>
      <Sidebar
        currentView={currentView}
        onViewChange={handleViewChange}
        activeSessionId={activeSessionId}
        onSessionSelect={handleSessionSelect}
        onNewSession={handleNewSession}
        projects={projects}
        activeProjectId={activeProjectId}
        onProjectChange={handleProjectChange}
        onProjectCreate={handleProjectCreate}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        refreshKey={sessionRefreshKey}
        modelSwitcher={currentView === "chat" ? (
          <ModelSwitcher
            onBrowseAll={handleBrowseAll}
            collapsed={sidebarCollapsed}
          />
        ) : undefined}
      />

      <div className="app-main" style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0, overflow: "hidden" }}>
        {currentView === "chat" && (missingAutomation || missingFullDisk) && (
          <PermissionsBanner
            missingAutomation={missingAutomation}
            missingFullDisk={missingFullDisk}
            onRetry={handlePermissionsRetry}
          />
        )}
        {currentView === "chat" && (
          <ChatView
            sessionId={activeSessionId}
            onSessionCreated={handleChatSessionCreated}
            onTitleUpdated={handleTitleUpdated}
            currentModelId={currentModelId}
          />
        )}
        {currentView === "compare" && (
          <CompareView
            key={comparisonSurfaceKey}
            sessionId={activeSessionId}
            projectId={activeProjectId}
            initialModels={draftLineup}
            onDraftModelsChange={setDraftLineup}
            onSessionCreated={handleCompareSessionCreated}
            onSessionDetached={handleCompareSessionDetached}
            onComparisonComplete={handleComparisonComplete}
            onBrowseModels={handleBrowseForComparison}
          />
        )}
        {currentView === "models" && (
          <ModelsView
            mode={modelBrowserMode}
            initialTab={modelBrowserMode === "add-to-comparison" ? "hub" : "library"}
            draftModels={draftLineup}
            maxModels={3}
            onAddModel={handleAddDraftModel}
            onRemoveModel={handleRemoveDraftModel}
            onReturn={handleReturnToComparison}
          />
        )}
        {currentView === "settings" && <SettingsView />}
      </div>
    </div>
  );
}
