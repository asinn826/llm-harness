import { useState, useCallback } from "react";
import { Sidebar } from "./components/Sidebar";
import { ModelSwitcher } from "./components/ModelSwitcher";
import { ChatView } from "./views/ChatView";
import { CompareView } from "./views/CompareView";
import { SessionsView } from "./views/SessionsView";

type View = "chat" | "compare" | "sessions" | "settings";

export default function App() {
  const [currentView, setCurrentView] = useState<View>("chat");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [currentModelId, setCurrentModelId] = useState<string | null>(null);
  const [currentBackend, setCurrentBackend] = useState<string | null>(null);
  // Bumped to trigger sidebar session list refresh
  const [sessionRefreshKey, setSessionRefreshKey] = useState(0);

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

  const handleResumeSession = useCallback((id: string) => {
    setActiveSessionId(id);
    setCurrentView("chat");
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
        {currentView === "chat" && (
          <ChatView
            sessionId={activeSessionId}
            onSessionCreated={handleSessionCreated}
            onTitleUpdated={handleTitleUpdated}
            currentModelId={currentModelId}
          />
        )}
        {currentView === "compare" && <CompareView />}
        {currentView === "sessions" && <SessionsView onResumeSession={handleResumeSession} />}
        {currentView === "settings" && (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ textAlign: "center", color: "var(--text-muted)", fontSize: 14 }}>
              Settings coming soon
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
