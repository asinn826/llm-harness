import { useState, useEffect, useCallback, useRef } from "react";
import { Plus, X, AlertTriangle, Loader2, Library, Lock } from "lucide-react";
import { ChatInput } from "../components/ChatInput";
import { ChatMessage, ToolCallApproval } from "../components/ChatMessage";
import { StatusNotice } from "../components/StatusNotice";
import { useWebSocket } from "../hooks/useWebSocket";
import { useDownloads } from "../contexts/DownloadsContext";
import { getErrorMessage, models as modelsApi, sessions as sessionsApi } from "../lib/api";
import { getTransferKey } from "../lib/transfers";
import type {
  ComparisonModelInput,
  Message,
  ModelInfo,
  SessionVisualState,
  WSServerMessage,
} from "../lib/types";
import { getModelColor } from "../lib/types";

interface PanelMessage {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  toolName?: string | null;
  toolArgs?: Record<string, unknown> | null;
  tokensGenerated?: number | null;
  generationTimeMs?: number | null;
}

interface PanelState {
  modelId: string;
  status: "idle" | "waiting" | "generating" | "done";
  messages: PanelMessage[];
  streamingContent: string;
  tokens?: number;
  timeMs?: number;
}

interface PendingToolCall {
  index: number;
  tool: string;
  args: Record<string, unknown>;
}

interface CompareViewProps {
  sessionId: string | null;
  projectId: string;
  initialModels: ComparisonModelInput[];
  onDraftModelsChange: (models: ComparisonModelInput[]) => void;
  onSessionCreated: (sessionId: string) => void;
  onSessionDetached: () => void;
  onComparisonComplete?: () => void;
  onRunStateChange?: (sessionId: string, state: SessionVisualState | null) => void;
  onBrowseModels?: () => void;
}

function panelsFromHistory(modelIds: string[], messages: Message[]): PanelState[] {
  return modelIds.map((modelId) => ({
    modelId,
    status: "idle",
    streamingContent: "",
    messages: messages
      .filter((message) => {
        if (message.role === "user") return true;
        if (message.model_id !== modelId) return false;
        // Tool-call syntax is an implementation detail; the persisted result is
        // the useful artifact to show when a comparison is reopened.
        return !(message.role === "assistant" && message.tool_name);
      })
      .map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        toolName: message.tool_name,
        toolArgs: message.tool_args,
        tokensGenerated: message.tokens_generated,
        generationTimeMs: message.generation_time_ms,
      })),
  }));
}

export function CompareView({
  sessionId,
  projectId,
  initialModels,
  onDraftModelsChange,
  onSessionCreated,
  onSessionDetached,
  onComparisonComplete,
  onRunStateChange,
  onBrowseModels,
}: CompareViewProps) {
  const [selectedModels, setSelectedModels] = useState<ComparisonModelInput[]>(
    () => sessionId ? [] : initialModels
  );
  const [available, setAvailable] = useState<ModelInfo[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(true);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const [panels, setPanels] = useState<PanelState[]>(
    () => sessionId ? [] : panelsFromHistory(initialModels.map((model) => model.model_id), [])
  );
  const [isRunning, setIsRunning] = useState(false);
  const [isLoadingThread, setIsLoadingThread] = useState(Boolean(sessionId));
  const [threadError, setThreadError] = useState<string | null>(null);
  const [threadRetryKey, setThreadRetryKey] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [lineupNotice, setLineupNotice] = useState<string | null>(null);
  const [showPicker, setShowPicker] = useState(false);
  const [checkingModelId, setCheckingModelId] = useState<string | null>(null);
  const [pendingToolCall, setPendingToolCall] = useState<PendingToolCall | null>(null);
  const streamingRefs = useRef<Record<number, string>>({});
  const pendingToolArgs = useRef<Record<number, Record<string, unknown>>>({});
  const createdSessionRef = useRef<string | null>(null);
  const loadedHistoryRef = useRef<Message[]>([]);
  const { downloads } = useDownloads();

  const loadAvailableModels = useCallback(async () => {
    setLibraryLoading(true);
    setLibraryError(null);
    try {
      const data = await modelsApi.list();
      const unique = new Map<string, ModelInfo>();
      [...data.cached, ...data.recommended].forEach((model) => {
        if (!unique.has(model.id)) unique.set(model.id, model);
      });
      setAvailable([...unique.values()]);
    } catch (loadError) {
      setLibraryError(getErrorMessage(loadError, "Couldn’t load the model library."));
    } finally {
      setLibraryLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadAvailableModels(); }, 0);
    return () => window.clearTimeout(timer);
  }, [loadAvailableModels]);

  useEffect(() => {
    let active = true;
    if (!sessionId || createdSessionRef.current === sessionId) return;
    const timer = window.setTimeout(() => {
      if (!active) return;
      setIsLoadingThread(true);
      setThreadError(null);

      Promise.all([sessionsApi.get(sessionId), sessionsApi.messages(sessionId)])
        .then(([session, messages]) => {
          if (!active) return;
          if (!session.is_compare) {
            setThreadError("This item is not a comparison.");
            return;
          }
          loadedHistoryRef.current = messages;
          setLineupNotice(null);
          const restoredModels = session.comparison_models.length > 0
            ? session.comparison_models.map((model) => ({
                model_id: model.model_id,
                backend: model.backend,
                revision: model.revision,
              }))
            : session.models.map((modelId) => ({ model_id: modelId }));
          setSelectedModels(restoredModels);
          setPanels(panelsFromHistory(session.models, messages));
        })
        .catch((loadError) => {
          if (!active) return;
          setThreadError(getErrorMessage(loadError, "Couldn’t open this comparison."));
        })
        .finally(() => {
          if (active) setIsLoadingThread(false);
        });
    }, 0);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [sessionId, threadRetryKey]);

  const handleWsMessage = useCallback(
    (msg: WSServerMessage) => {
      switch (msg.type) {
        case "session_created":
          createdSessionRef.current = msg.session_id;
          onSessionCreated(msg.session_id);
          onRunStateChange?.(msg.session_id, "running");
          break;

        case "model_start": {
          const idx = msg.index;
          streamingRefs.current[idx] = "";
          setPanels((current) =>
            current.map((panel, index) => (
              index === idx
                ? { ...panel, status: "generating", streamingContent: "" }
                : panel
            ))
          );
          break;
        }

        case "token": {
          if (msg.index === undefined) break;
          const idx = msg.index;
          streamingRefs.current[idx] = (streamingRefs.current[idx] || "") + msg.data;
          const content = streamingRefs.current[idx];
          setPanels((current) =>
            current.map((panel, index) => (
              index === idx ? { ...panel, streamingContent: content } : panel
            ))
          );
          break;
        }

        case "tool_call": {
          if (msg.index === undefined) break;
          const idx = msg.index;
          pendingToolArgs.current[idx] = msg.args;
          // The streamed content is the model's tool-call envelope, not an
          // answer. Keep it out of the comparison transcript.
          streamingRefs.current[idx] = "";
          setPanels((current) =>
            current.map((panel, index) => (
              index === idx ? { ...panel, streamingContent: "" } : panel
            ))
          );
          if (msg.needs_confirmation) {
            setPendingToolCall({ index: idx, tool: msg.tool, args: msg.args });
          }
          break;
        }

        case "tool_result": {
          if (msg.index === undefined) break;
          const idx = msg.index;
          setPanels((current) =>
            current.map((panel, index) => (
              index === idx
                ? {
                    ...panel,
                    messages: [
                      ...panel.messages,
                      {
                        id: `tool-${idx}-${Date.now()}`,
                        role: "tool",
                        content: msg.result,
                        toolName: msg.tool,
                        toolArgs: msg.args ?? pendingToolArgs.current[idx],
                      },
                    ],
                  }
                : panel
            ))
          );
          setPendingToolCall((current) => current?.index === idx ? null : current);
          break;
        }

        case "model_done": {
          const idx = msg.index;
          const failed = msg.response.startsWith("Error ") ||
            msg.response === "Model returned empty response";
          const finalContent = failed
            ? msg.response
            : streamingRefs.current[idx]?.trim() || msg.response;
          setPanels((current) =>
            current.map((panel, index) => (
              index === idx
                ? {
                    ...panel,
                    status: "done",
                    tokens: msg.tokens,
                    timeMs: msg.time_ms,
                    streamingContent: "",
                    messages: finalContent
                      ? [
                          ...panel.messages,
                          {
                            id: `done-${idx}-${Date.now()}`,
                            role: "assistant",
                            content: finalContent,
                            tokensGenerated: msg.tokens,
                            generationTimeMs: msg.time_ms,
                          },
                        ]
                      : panel.messages,
                  }
                : panel
            ))
          );
          streamingRefs.current[idx] = "";
          setPendingToolCall((current) => current?.index === idx ? null : current);
          break;
        }

        case "compare_done":
          setPendingToolCall(null);
          setIsRunning(false);
          onRunStateChange?.(msg.session_id, document.visibilityState === "visible" ? null : "unread");
          onComparisonComplete?.();
          break;

        case "error":
          setPendingToolCall(null);
          setError(msg.message);
          setIsRunning(false);
          if (createdSessionRef.current ?? sessionId) {
            onRunStateChange?.((createdSessionRef.current ?? sessionId) as string, "failed");
          }
          break;
      }
    },
    [onComparisonComplete, onRunStateChange, onSessionCreated, sessionId]
  );

  const handleDisconnect = useCallback(() => {
    if (!isRunning) return;
    setPendingToolCall(null);
    setIsRunning(false);
    setError("The comparison connection was interrupted. Your completed model outcomes are still saved.");
    if (createdSessionRef.current ?? sessionId) {
      onRunStateChange?.((createdSessionRef.current ?? sessionId) as string, "failed");
    }
  }, [isRunning, onRunStateChange, sessionId]);

  const { send, state: wsState, connect } = useWebSocket({
    path: "/ws/compare",
    onMessage: handleWsMessage,
    onDisconnect: handleDisconnect,
  });

  const approveToolCall = useCallback(() => {
    send({ type: "tool_response", approved: true });
    setPendingToolCall(null);
  }, [send]);

  const denyToolCall = useCallback(() => {
    send({ type: "tool_response", approved: false });
    setPendingToolCall(null);
  }, [send]);

  // Complete persisted lineups stay immutable for fair history. Legacy or
  // interrupted one-model sessions can be repaired by forking into a draft.
  const lineupLocked = Boolean(sessionId && selectedModels.length >= 2);

  const addModel = async (modelId: string) => {
    if (
      lineupLocked ||
      selectedModels.length >= 3 ||
      selectedModels.some((model) => model.model_id === modelId)
    ) return;
    const availableModel = available.find((model) => model.id === modelId);
    if (!availableModel) return;
    setCheckingModelId(modelId);
    setError(null);
    try {
      const preflight = await modelsApi.preflight({
        model_id: modelId,
        backend: availableModel.backend,
        revision: "main",
      });
      if (!preflight.can_load || !preflight.resolved_revision) {
        setError(preflight.error?.message ?? `${modelId} cannot run in this harness.`);
        return;
      }
      if (preflight.cache_status && preflight.cache_status !== "complete") {
        setError(`${modelId} is not fully installed. Open the model browser to install and add it.`);
        return;
      }
      const nextModels = [...selectedModels, {
        model_id: modelId,
        backend: preflight.backend,
        revision: preflight.resolved_revision,
      }];
      const repairingIncompleteSession = Boolean(sessionId && selectedModels.length === 1);
      setSelectedModels(nextModels);
      onDraftModelsChange(nextModels);
      if (repairingIncompleteSession) {
        // The backend intentionally keeps persisted lineups immutable. Start a
        // fresh draft so the repaired two-model lineup is what gets persisted.
        loadedHistoryRef.current = [];
        setPanels(panelsFromHistory(nextModels.map((model) => model.model_id), []));
        setLineupNotice("Changes will be saved as a new comparison.");
        onSessionDetached();
      } else {
        setPanels((current) => [
          ...current,
          panelsFromHistory([modelId], loadedHistoryRef.current)[0],
        ]);
      }
      setShowPicker(false);
    } catch (preflightError) {
      setError(getErrorMessage(preflightError, "Couldn’t check this model."));
    } finally {
      setCheckingModelId(null);
    }
  };

  const removeModel = (modelId: string) => {
    if (lineupLocked || sessionId) return;
    const nextModels = selectedModels.filter((candidate) => candidate.model_id !== modelId);
    setSelectedModels(nextModels);
    onDraftModelsChange(nextModels);
    setPanels((current) => current.filter((panel) => panel.modelId !== modelId));
  };

  const handleBrowseModels = () => {
    if (sessionId && selectedModels.length === 1) {
      // Carry the recoverable model into a new draft before leaving this view.
      loadedHistoryRef.current = [];
      onDraftModelsChange(selectedModels);
      onSessionDetached();
    }
    onBrowseModels?.();
  };

  const handleSend = (content: string) => {
    if (selectedModels.length < 2 || isRunning) return;

    setError(null);
    setIsRunning(true);
    if (sessionId) onRunStateChange?.(sessionId, "running");
    streamingRefs.current = {};
    pendingToolArgs.current = {};
    setPendingToolCall(null);
    setPanels((current) => selectedModels.map((modelSpec) => {
      const modelId = modelSpec.model_id;
      const existing = current.find((panel) => panel.modelId === modelId);
      return {
        modelId,
        status: "waiting",
        messages: [
          ...(existing?.messages ?? []),
          {
            id: `user-${modelId}-${Date.now()}`,
            role: "user",
            content,
          } as PanelMessage,
        ],
        streamingContent: "",
      };
    }));

    send({
      type: "message",
      content,
      models: selectedModels,
      session_id: sessionId ?? undefined,
      project_id: projectId,
    });
  };

  const unselectedModels = available.filter(
    (model) => model.is_cached && !selectedModels.some((selected) => selected.model_id === model.id)
  );
  const selectedTransfers = selectedModels
    .map((model) => downloads[getTransferKey(
      model.model_id,
      model.backend,
      model.revision,
    )])
    .filter(Boolean);
  const installPending = selectedTransfers.some(
    (transfer) => transfer.status === "downloading" || transfer.status === "loading"
  );
  const installFailed = selectedTransfers.some((transfer) => transfer.status === "error");
  const composerDescription = installFailed
    ? "A selected model failed to install. Open Models to review it."
    : installPending
      ? "The comparison will be available when every model finishes installing."
      : selectedModels.length < 2
        ? undefined
        : wsState === "connecting"
          ? "Connecting to the local Harness service…"
          : wsState !== "open"
            ? "Harness is offline. Reconnect before running the comparison."
            : "Enter one prompt to run it across the selected models.";

  return (
    <div className="compare-view flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      {/* Stable model lineup */}
      <header className="compare-toolbar flex items-center gap-2 border-b border-[var(--border-subtle)] bg-[var(--bg-secondary)] px-4 py-2.5">
        <span className="compare-toolbar-label text-[var(--text-muted)]">Models</span>
        {selectedModels.map((modelSpec) => {
          const modelId = modelSpec.model_id;
          const transfer = downloads[getTransferKey(
            modelId,
            modelSpec.backend,
            modelSpec.revision,
          )];
          return (
          <span
            key={modelId}
            className="lineup-model inline-flex items-center gap-1.5 text-sm"
            style={{ color: "var(--text-primary)" }}
            title={modelSpec.revision ? `${modelId}@${modelSpec.revision}` : modelId}
          >
            <span className="h-2 w-2 rounded-full" style={{ background: getModelColor(modelId) }} />
            {modelId.split("/").pop()}
            {modelSpec.revision && (
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                @{modelSpec.revision.slice(0, 7)}
              </span>
            )}
            {transfer && (transfer.status === "downloading" || transfer.status === "loading") && (
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                {Math.round(transfer.progress * 100)}%
              </span>
            )}
            {transfer?.status === "error" && (
              <AlertTriangle size={10} style={{ color: "var(--error)" }} />
            )}
            {!lineupLocked && !sessionId && (
              <button type="button" onClick={() => removeModel(modelId)} className="hover:opacity-70" aria-label={`Remove ${modelId}`}>
                <X size={12} />
              </button>
            )}
          </span>
          );
        })}
        {!lineupLocked && selectedModels.length < 3 && (
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowPicker((current) => !current)}
              aria-expanded={showPicker}
              aria-haspopup="menu"
              className="lineup-add inline-flex items-center gap-1 border border-[var(--border-default)] text-sm text-[var(--text-secondary)] transition-colors duration-[var(--duration-fast)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-secondary)]"
            >
              <Plus size={14} /> {selectedModels.length === 0 ? "Choose models" : "Add model"}
            </button>
            {showPicker && (
              <div role="menu" aria-label="Available models" className="absolute left-0 top-full z-50 mt-1 max-h-[calc(100vh-120px)] min-w-[270px] overflow-y-auto rounded-sm border border-[var(--border-default)] bg-[var(--bg-tertiary)] shadow-md">
                {unselectedModels.length === 0 ? (
                  <div className="model-picker-empty">
                    <strong>{libraryLoading ? "Loading models…" : "No downloaded models available"}</strong>
                    {!libraryLoading && <span>Browse the Hub to find and install a model.</span>}
                  </div>
                ) : (
                  unselectedModels.map((model) => (
                    <button
                      key={model.id}
                      type="button"
                      role="menuitem"
                      onClick={() => addModel(model.id)}
                      disabled={checkingModelId !== null}
                      className="model-picker-option w-full px-3 py-2 text-left text-sm text-[var(--text-secondary)]"
                    >
                      <div className="flex items-center gap-1.5">
                        {checkingModelId === model.id && <Loader2 size={10} className="animate-spin" />}
                        {model.name || model.id.split("/").pop()}
                      </div>
                      <div className="mt-0.5 truncate text-xs text-[var(--text-muted)]">{model.id}</div>
                    </button>
                  ))
                )}
                {onBrowseModels && (
                  <button
                    type="button"
                    onClick={handleBrowseModels}
                    className="flex w-full items-center gap-1.5 border-t border-[var(--border-subtle)] px-3 py-2 text-left text-sm text-[var(--accent)] hover:bg-[var(--bg-surface)]"
                  >
                    <Library size={14} /> Browse models
                  </button>
                )}
              </div>
            )}
          </div>
        )}
        {lineupLocked && (
          <span className="flex items-center text-[var(--text-muted)]" title="Models cannot be changed in this comparison" aria-label="Models cannot be changed in this comparison">
            <Lock size={12} />
          </span>
        )}
      </header>

      {error && (
        <StatusNotice tone="error" title="Comparison couldn’t continue" message={error} compact />
      )}

      {libraryError && (
        <StatusNotice
          tone="offline"
          title="Model library unavailable"
          message={libraryError}
          actionLabel="Retry"
          onAction={() => void loadAvailableModels()}
          compact
        />
      )}

      {!libraryError && wsState !== "open" && !isLoadingThread && (
        <StatusNotice
          tone={wsState === "connecting" ? "info" : "offline"}
          title={wsState === "connecting" ? "Connecting to Harness" : "Harness is offline"}
          message={wsState === "connecting" ? "The prompt will unlock when the local service is ready." : "Completed results remain saved while Harness reconnects."}
          actionLabel={wsState === "connecting" ? undefined : "Reconnect"}
          onAction={wsState === "connecting" ? undefined : connect}
          compact
        />
      )}

      {lineupNotice && (
        <div className="border-b border-[var(--border-subtle)] bg-[var(--bg-secondary)] px-4 py-2 text-xs text-[var(--text-muted)]">
          {lineupNotice}
        </div>
      )}

      {installPending && (
        <div className="border-b border-[var(--border-subtle)] bg-[var(--bg-secondary)] px-4 py-2 text-xs text-[var(--text-muted)]">
          Installing model…
        </div>
      )}

      {/* Side-by-side transcript */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {isLoadingThread && (
          <div className="flex flex-1 items-center justify-center text-sm text-[var(--text-muted)]">
            <Loader2 size={14} className="mr-2 animate-spin" /> Opening comparison…
          </div>
        )}

        {!isLoadingThread && threadError && (
          <div className="comparison-state-wrap">
            <StatusNotice
              tone="offline"
              title="Couldn’t open this comparison"
              message={threadError}
              actionLabel="Retry"
              onAction={() => setThreadRetryKey((key) => key + 1)}
            />
          </div>
        )}

        {!isLoadingThread && !threadError && panels.length === 0 && (
          <div className="comparison-empty">Responses appear here.</div>
        )}

        {!isLoadingThread && !threadError && panels.map((panel, idx) => (
          <div
            key={panel.modelId}
            className={`flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden ${idx > 0 ? "border-l border-[var(--border-subtle)]" : ""}`}
            role="region"
            aria-label={`${panel.modelId} response`}
          >
            <div
              className="panel-header flex items-center gap-2 border-b border-[var(--border-subtle)] px-3 py-2"
              style={{ background: `${getModelColor(panel.modelId)}08` }}
            >
              <div className="h-2 w-2 rounded-full" style={{ background: getModelColor(panel.modelId) }} />
              <span className="truncate text-sm font-medium text-[var(--text-primary)]" title={panel.modelId}>
                {panel.modelId.split("/").pop()}
              </span>
              <div className="flex-1" />
              {panel.status === "waiting" && <span className="text-xs text-[var(--text-muted)]">Waiting…</span>}
              {panel.status === "generating" && <Loader2 size={12} className="animate-spin text-[var(--accent)]" />}
              {panel.status === "done" && panel.timeMs !== undefined && (
                <span className="text-xs text-[var(--text-muted)]">
                  {(panel.timeMs / 1000).toFixed(1)}s · {panel.tokens ?? 0} tok
                </span>
              )}
            </div>

            <PanelTranscript
              panel={panel}
              pendingToolCall={pendingToolCall?.index === idx ? pendingToolCall : null}
              onApproveTool={approveToolCall}
              onDenyTool={denyToolCall}
            />
          </div>
        ))}
      </div>

      <div className="mx-auto w-full max-w-4xl shrink-0">
        <ChatInput
          onSend={handleSend}
          disabled={isRunning || selectedModels.length < 2 || installPending || installFailed || wsState !== "open" || isLoadingThread}
          placeholder={
            installFailed
              ? "Model install failed"
              : installPending
                ? "Installing model…"
                : selectedModels.length === 0
                  ? "Select two models above"
                  : selectedModels.length === 1
                    ? "Select one more model above"
                    : isRunning
                      ? "Running…"
                      : "Prompt"
          }
          description={composerDescription}
          actionLabel={wsState === "open" ? undefined : "Reconnect"}
          onAction={wsState === "open" ? undefined : connect}
          ariaLabel="Comparison prompt"
        />
      </div>
    </div>
  );
}

function PanelTranscript({
  panel,
  pendingToolCall,
  onApproveTool,
  onDenyTool,
}: {
  panel: PanelState;
  pendingToolCall: PendingToolCall | null;
  onApproveTool: () => void;
  onDenyTool: () => void;
}) {
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (transcript) {
      transcript.scrollTop = transcript.scrollHeight;
    }
  }, [panel.messages.length, panel.streamingContent, pendingToolCall]);

  return (
    <div ref={transcriptRef} className="min-h-0 flex-1 overflow-y-auto py-2">
      {panel.messages.length === 0 && !panel.streamingContent && (
        <div />
      )}
      {panel.messages.map((message) => (
        <ChatMessage
          key={message.id}
          role={message.role}
          content={message.content}
          modelId={panel.modelId}
          toolName={message.toolName}
          toolArgs={message.toolArgs}
          tokensGenerated={message.tokensGenerated}
          generationTimeMs={message.generationTimeMs}
        />
      ))}
      {panel.streamingContent && (
        <ChatMessage role="assistant" content={panel.streamingContent} modelId={panel.modelId} isStreaming />
      )}
      {pendingToolCall && (
        <ToolCallApproval
          toolName={pendingToolCall.tool}
          args={pendingToolCall.args}
          onApprove={onApproveTool}
          onDeny={onDenyTool}
        />
      )}
    </div>
  );
}
