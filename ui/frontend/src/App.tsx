import { useState, useCallback, useEffect } from "react";
import { Sidebar } from "./components/Sidebar";
import { ModelSwitcher } from "./components/ModelSwitcher";
import { PermissionsBanner } from "./components/PermissionsBanner";
import { ChatView } from "./views/ChatView";
import { CompareView } from "./views/CompareView";
import { SettingsView } from "./views/SettingsView";

type View = "chat" | "compare" | "settings";

export default function App() {
  const [currentView, setCurrentView] = useState<View>("chat");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [currentModelId, setCurrentModelId] = useState<string | null>(null);
  const [currentBackend, setCurrentBackend] = useState<string | null>(null);
  const [sessionRefreshKey, setSessionRefreshKey] = useState(0);
  const [missingAutomation, setMissingAutomation] = useState(false);
  const [missingFullDisk, setMissingFullDisk] = useState(false);

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

  const handleModelLoaded = useCallback((modelId: string, backend: string) => {
    setCurrentModelId(modelId);
    setCurrentBackend(backend);
  }, []);

  const handleNewSession = useCallback(() => {
    setActiveSessionId(null);
    setCurrentView("chat");
  }, []);

  const handleSessionSelect = useCallback((id: string) => {
    setActiveSessionId(id);
    setCurrentView("chat");
  }, []);

  const handleSessionCreated = useCallback((id: string) => {
    setActiveSessionId(id);
    setSessionRefreshKey((k) => k + 1);
  }, []);

  const handleTitleUpdated = useCallback((_sessionId: string, _title: string) => {
    setSessionRefreshKey((k) => k + 1);
  }, []);

  const handlePermissionsRetry = useCallback(() => {
    fetch("/api/permissions")
      .then((r) => r.json())
      .then((data) => {
        setMissingAutomation(!data.messages || !data.contacts);
        setMissingFullDisk(!data.full_disk_access);
      })
      .catch(() => {});
  }, []);

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", background: "var(--bg-primary)" }}>
      <Sidebar
        currentView={currentView}
        onViewChange={setCurrentView}
        activeSessionId={activeSessionId}
        onSessionSelect={handleSessionSelect}
        onNewSession={handleNewSession}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        refreshKey={sessionRefreshKey}
        modelSwitcher={
          <ModelSwitcher
            onModelLoaded={handleModelLoaded}
            collapsed={sidebarCollapsed}
          />
        }
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "hidden" }}>
        {(missingAutomation || missingFullDisk) && (
          <PermissionsBanner
            missingAutomation={missingAutomation}
            missingFullDisk={missingFullDisk}
            onRetry={handlePermissionsRetry}
          />
        )}
        {currentView === "chat" && (
          <ChatView
            sessionId={activeSessionId}
            onSessionCreated={handleSessionCreated}
            onTitleUpdated={handleTitleUpdated}
            currentModelId={currentModelId}
          />
        )}
        {currentView === "compare" && <CompareView />}
        {currentView === "settings" && <SettingsView />}
      </div>
    </div>
  );
}
