import { useState, useEffect, useCallback, useRef } from "react";
import { Plus, X, AlertTriangle, Loader2 } from "lucide-react";
import { ChatInput } from "../components/ChatInput";
import { ChatMessage } from "../components/ChatMessage";
import { useWebSocket } from "../hooks/useWebSocket";
import { models as modelsApi } from "../lib/api";
import type { ModelInfo, WSServerMessage } from "../lib/types";
import { getModelColor } from "../lib/types";

interface PanelState {
  modelId: string;
  status: "idle" | "waiting" | "generating" | "done";
  messages: Array<{
    id: string;
    role: "assistant" | "tool";
    content: string;
    toolName?: string;
    toolArgs?: Record<string, unknown>;
  }>;
  streamingContent: string;
  tokens?: number;
  timeMs?: number;
}

export function CompareView() {
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [available, setAvailable] = useState<ModelInfo[]>([]);
  const [panels, setPanels] = useState<PanelState[]>([]);
  const [userMessage, setUserMessage] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const streamingRefs = useRef<Record<number, string>>({});

  useEffect(() => {
    modelsApi.list().then((data) => {
      setAvailable([...data.recommended, ...data.cached]);
    });
  }, []);

  const handleWsMessage = useCallback(
    (msg: WSServerMessage) => {
      switch (msg.type) {
        case "model_start": {
          const idx = ("index" in msg ? (msg as any).index : -1) as number;
          streamingRefs.current[idx] = "";
          setPanels((prev) =>
            prev.map((p, i) => (i === idx ? { ...p, status: "generating", streamingContent: "" } : p))
          );
          break;
        }

        case "token": {
          const idx = ("index" in msg ? (msg as any).index : -1) as number;
          streamingRefs.current[idx] = (streamingRefs.current[idx] || "") + msg.data;
          const content = streamingRefs.current[idx];
          setPanels((prev) =>
            prev.map((p, i) => (i === idx ? { ...p, streamingContent: content } : p))
          );
          break;
        }

        case "tool_call": {
          const idx = ("index" in msg ? (msg as any).index : -1) as number;
          // For compare, auto-approve read-only, display for others
          if (streamingRefs.current[idx]) {
            setPanels((prev) =>
              prev.map((p, i) =>
                i === idx
                  ? {
                      ...p,
                      messages: [
                        ...p.messages,
                        { id: `ast-${Date.now()}`, role: "assistant", content: streamingRefs.current[idx] },
                      ],
                      streamingContent: "",
                    }
                  : p
              )
            );
            streamingRefs.current[idx] = "";
          }
          break;
        }

        case "tool_result": {
          const idx = ("index" in msg ? (msg as any).index : -1) as number;
          setPanels((prev) =>
            prev.map((p, i) =>
              i === idx
                ? {
                    ...p,
                    messages: [
                      ...p.messages,
                      { id: `tool-${Date.now()}`, role: "tool", content: msg.result, toolName: msg.tool },
                    ],
                  }
                : p
            )
          );
          break;
        }

        case "model_done": {
          const idx = ("index" in msg ? (msg as any).index : -1) as number;
          const finalContent = streamingRefs.current[idx] || "";
          setPanels((prev) =>
            prev.map((p, i) =>
              i === idx
                ? {
                    ...p,
                    status: "done",
                    tokens: msg.tokens,
                    timeMs: msg.time_ms,
                    streamingContent: "",
                    messages: finalContent
                      ? [
                          ...p.messages,
                          { id: `done-${Date.now()}`, role: "assistant", content: finalContent },
                        ]
                      : p.messages,
                  }
                : p
            )
          );
          streamingRefs.current[idx] = "";
          break;
        }

        case "compare_done":
          setIsRunning(false);
          break;

        case "error":
          setIsRunning(false);
          break;
      }
    },
    []
  );

  const { send, state: wsState } = useWebSocket({
    path: "/ws/compare",
    onMessage: handleWsMessage,
  });

  const addModel = (modelId: string) => {
    if (selectedModels.length >= 3 || selectedModels.includes(modelId)) return;
    setSelectedModels((prev) => [...prev, modelId]);
    setShowPicker(false);
  };

  const removeModel = (modelId: string) => {
    setSelectedModels((prev) => prev.filter((m) => m !== modelId));
  };

  const handleSend = (content: string) => {
    if (selectedModels.length < 2) return;

    setUserMessage(content);
    setIsRunning(true);
    streamingRefs.current = {};
    setPanels(
      selectedModels.map((modelId) => ({
        modelId,
        status: "waiting",
        messages: [],
        streamingContent: "",
      }))
    );

    send({
      type: "message",
      content,
      models: selectedModels,
    } as any);
  };

  const unselectedModels = available.filter((m) => !selectedModels.includes(m.id));

  return (
    <div className="flex-1 flex flex-col min-w-0">
      {/* Model selector bar */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--border-subtle)] bg-[var(--bg-secondary)]">
        <span className="text-xs text-[var(--text-muted)]">Comparing:</span>
        {selectedModels.map((modelId) => (
          <span
            key={modelId}
            className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border"
            style={{
              borderColor: `${getModelColor(modelId)}40`,
              background: `${getModelColor(modelId)}15`,
              color: getModelColor(modelId),
            }}
          >
            {modelId.split("/").pop()}
            <button onClick={() => removeModel(modelId)} className="hover:opacity-70">
              <X size={12} />
            </button>
          </span>
        ))}
        {selectedModels.length < 3 && (
          <div className="relative">
            <button
              onClick={() => setShowPicker(!showPicker)}
              className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border border-dashed border-[var(--border-default)] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:border-[var(--border-strong)] transition-colors duration-[var(--duration-fast)]"
            >
              <Plus size={12} /> Add model
            </button>
            {showPicker && unselectedModels.length > 0 && (
              <div className="absolute left-0 top-full mt-1 z-50 bg-[var(--bg-tertiary)] border border-[var(--border-default)] rounded-lg shadow-lg overflow-hidden min-w-[200px]">
                {unselectedModels.map((model) => (
                  <button
                    key={model.id}
                    onClick={() => addModel(model.id)}
                    className="w-full text-left px-3 py-2 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
                  >
                    {model.name || model.id.split("/").pop()}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="flex-1" />
        <span className="text-[10px] text-[var(--text-muted)] flex items-center gap-1">
          <AlertTriangle size={10} /> Models run sequentially
        </span>
      </div>

      {/* Panels */}
      <div className="flex-1 flex overflow-hidden">
        {panels.length === 0 && (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <div className="text-[var(--text-tertiary)] text-sm mb-1">
                {selectedModels.length < 2
                  ? "Select at least 2 models to compare"
                  : "Send a message to start comparing"}
              </div>
            </div>
          </div>
        )}

        {panels.map((panel, idx) => (
          <div
            key={panel.modelId}
            className={`flex-1 flex flex-col min-w-0 ${idx > 0 ? "border-l border-[var(--border-subtle)]" : ""}`}
          >
            {/* Panel header */}
            <div
              className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border-subtle)]"
              style={{ background: `${getModelColor(panel.modelId)}08` }}
            >
              <div
                className="w-2 h-2 rounded-full"
                style={{ background: getModelColor(panel.modelId) }}
              />
              <span
                className="text-xs font-medium"
                style={{ color: getModelColor(panel.modelId) }}
              >
                {panel.modelId.split("/").pop()}
              </span>
              <div className="flex-1" />
              {panel.status === "waiting" && (
                <span className="text-[10px] text-[var(--text-muted)]">Waiting...</span>
              )}
              {panel.status === "generating" && (
                <Loader2 size={12} className="text-[var(--accent)] animate-spin" />
              )}
              {panel.status === "done" && panel.tokens && panel.timeMs && (
                <span className="text-[10px] text-[var(--text-muted)]">
                  {(panel.timeMs / 1000).toFixed(1)}s · {panel.tokens} tok
                </span>
              )}
            </div>

            {/* Panel messages */}
            <div className="flex-1 overflow-y-auto py-2">
              {/* User message (shared) */}
              {userMessage && (
                <ChatMessage role="user" content={userMessage} />
              )}
              {panel.messages.map((msg) => (
                <ChatMessage
                  key={msg.id}
                  role={msg.role}
                  content={msg.content}
                  modelId={panel.modelId}
                  toolName={msg.toolName}
                  toolArgs={msg.toolArgs}
                />
              ))}
              {panel.streamingContent && (
                <ChatMessage
                  role="assistant"
                  content={panel.streamingContent}
                  modelId={panel.modelId}
                  isStreaming
                />
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Shared input */}
      <div className="max-w-3xl mx-auto w-full">
        <ChatInput
          onSend={handleSend}
          disabled={isRunning || selectedModels.length < 2 || wsState !== "open"}
          placeholder={
            selectedModels.length < 2
              ? "Select at least 2 models..."
              : isRunning
                ? "Comparing..."
                : "Same prompt goes to all models..."
          }
        />
      </div>
    </div>
  );
}
