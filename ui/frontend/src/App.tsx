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

  // Auto-collapse sidebar for compare and models views
  const isCompactView = currentView === "compare" || currentView === "models";
  const effectiveCollapsed = isCompactView || sidebarCollapsed;

  return (
    <div className="flex h-screen bg-[var(--bg-primary)]">
      <Sidebar
        currentView={currentView}
        onViewChange={setCurrentView}
        activeSessionId={activeSessionId}
        onSessionSelect={handleSessionSelect}
        onNewSession={handleNewSession}
        collapsed={effectiveCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      <div className="flex-1 flex flex-col min-w-0">
        {/* Model switcher in chat view */}
        {currentView === "chat" && !effectiveCollapsed && (
          <ModelSwitcher onModelLoaded={handleModelLoaded} />
        )}
        {currentView === "chat" && effectiveCollapsed && (
          <div className="flex items-center gap-3 px-4 py-2 border-b border-[var(--border-subtle)] bg-[var(--bg-secondary)]">
            <span className="text-sm font-semibold text-[var(--text-primary)] tracking-tight">
              Harness
            </span>
            <div className="w-px h-4 bg-[var(--border-subtle)]" />
            <ModelSwitcher onModelLoaded={handleModelLoaded} />
          </div>
        )}

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
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center text-[var(--text-muted)] text-sm">
              Settings coming soon
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
