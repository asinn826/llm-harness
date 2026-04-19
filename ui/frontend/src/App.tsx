import { useState, useCallback } from "react";
import { Sidebar } from "./components/Sidebar";
import { ModelSwitcher } from "./components/ModelSwitcher";
import { ChatView } from "./views/ChatView";
import { CompareView } from "./views/CompareView";
import { ModelsView } from "./views/ModelsView";
import { SessionsView } from "./views/SessionsView";

type View = "chat" | "compare" | "models" | "sessions" | "settings";

export default function App() {
  const [currentView, setCurrentView] = useState<View>("chat");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [currentModelId, setCurrentModelId] = useState<string | null>(null);
  const [currentBackend, setCurrentBackend] = useState<string | null>(null);

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
  }, []);

  const handleResumeSession = useCallback((id: string) => {
    setActiveSessionId(id);
    setCurrentView("chat");
  }, []);

  const isCompactView = currentView === "compare" || currentView === "models";
  const effectiveCollapsed = isCompactView || sidebarCollapsed;

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", background: "var(--bg-primary)" }}>
      <Sidebar
        currentView={currentView}
        onViewChange={setCurrentView}
        activeSessionId={activeSessionId}
        onSessionSelect={handleSessionSelect}
        onNewSession={handleNewSession}
        collapsed={effectiveCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        modelSwitcher={<ModelSwitcher onModelLoaded={handleModelLoaded} />}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "hidden" }}>
        {currentView === "chat" && (
          <ChatView
            sessionId={activeSessionId}
            onSessionCreated={handleSessionCreated}
            currentModelId={currentModelId}
          />
        )}
        {currentView === "compare" && <CompareView />}
        {currentView === "models" && <ModelsView onModelLoaded={handleModelLoaded} />}
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
