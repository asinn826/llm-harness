import { useState, useEffect, useCallback, useRef } from "react";
import { Plus, X, AlertTriangle, Loader2, Library, Lock } from "lucide-react";
import { ChatInput } from "../components/ChatInput";
import { ChatMessage } from "../components/ChatMessage";
import { useWebSocket } from "../hooks/useWebSocket";
import { useDownloads } from "../contexts/DownloadsContext";
import { models as modelsApi, sessions as sessionsApi } from "../lib/api";
import { getTransferKey } from "../lib/transfers";
import type {
  ComparisonModelInput,
  Message,
  ModelInfo,
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

interface CompareViewProps {
  sessionId: string | null;
  projectId: string;
  initialModels: ComparisonModelInput[];
  onDraftModelsChange: (models: ComparisonModelInput[]) => void;
  onSessionCreated: (sessionId: string) => void;
  onSessionDetached: () => void;
  onComparisonComplete?: () => void;
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
  onBrowseModels,
}: CompareViewProps) {
  const [selectedModels, setSelectedModels] = useState<ComparisonModelInput[]>(
    () => sessionId ? [] : initialModels
  );
  const [available, setAvailable] = useState<ModelInfo[]>([]);
  const [panels, setPanels] = useState<PanelState[]>(
    () => sessionId ? [] : panelsFromHistory(initialModels.map((model) => model.model_id), [])
  );
  const [isRunning, setIsRunning] = useState(false);
  const [isLoadingThread, setIsLoadingThread] = useState(Boolean(sessionId));
  const [error, setError] = useState<string | null>(null);
  const [lineupNotice, setLineupNotice] = useState<string | null>(null);
  const [showPicker, setShowPicker] = useState(false);
  const [checkingModelId, setCheckingModelId] = useState<string | null>(null);
  const streamingRefs = useRef<Record<number, string>>({});
  const pendingToolArgs = useRef<Record<number, Record<string, unknown>>>({});
  const createdSessionRef = useRef<string | null>(null);
  const loadedHistoryRef = useRef<Message[]>([]);
  const { downloads } = useDownloads();

  useEffect(() => {
    modelsApi.list().then((data) => {
      const unique = new Map<string, ModelInfo>();
      [...data.cached, ...data.recommended].forEach((model) => {
        if (!unique.has(model.id)) unique.set(model.id, model);
      });
      setAvailable([...unique.values()]);
    }).catch(() => setError("Could not load the model library"));
  }, []);

  useEffect(() => {
    let active = true;
    if (!sessionId || createdSessionRef.current === sessionId) return;

    Promise.all([sessionsApi.get(sessionId), sessionsApi.messages(sessionId)])
      .then(([session, messages]) => {
        if (!active) return;
        if (!session.is_compare) {
          setError("This session is not a comparison.");
          setSelectedModels([]);
          setPanels([]);
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
        setError(loadError instanceof Error ? loadError.message : "Could not open comparison");
      })
      .finally(() => {
        if (active) setIsLoadingThread(false);
      });

    return () => {
      active = false;
    };
  }, [sessionId]);

  const handleWsMessage = useCallback(
    (msg: WSServerMessage) => {
      switch (msg.type) {
        case "session_created":
          createdSessionRef.current = msg.session_id;
          onSessionCreated(msg.session_id);
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
                        toolArgs: pendingToolArgs.current[idx],
                      },
                    ],
                  }
                : panel
            ))
          );
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
          break;
        }

        case "compare_done":
          setIsRunning(false);
          onComparisonComplete?.();
          break;

        case "error":
          setError(msg.message);
          setIsRunning(false);
          break;
      }
    },
    [onComparisonComplete, onSessionCreated]
  );

  const handleDisconnect = useCallback(() => {
    if (!isRunning) return;
    setIsRunning(false);
    setError("The comparison connection was interrupted. Your completed model outcomes are still saved.");
  }, [isRunning]);

  const { send, state: wsState } = useWebSocket({
    path: "/ws/compare",
    onMessage: handleWsMessage,
    onDisconnect: handleDisconnect,
  });

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
        setLineupNotice("The incomplete one-model comparison was preserved. This repaired lineup will be saved as a new comparison.");
        onSessionDetached();
      } else {
        setPanels((current) => [
          ...current,
          panelsFromHistory([modelId], loadedHistoryRef.current)[0],
        ]);
      }
      setShowPicker(false);
    } catch (preflightError) {
      setError(preflightError instanceof Error ? preflightError.message : "Could not check this model");
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
    streamingRefs.current = {};
    pendingToolArgs.current = {};
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

  return (
    <div className="compare-view flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      {/* Stable model lineup */}
      <div className="compare-toolbar flex items-center gap-2 border-b border-[var(--border-subtle)] bg-[var(--bg-secondary)] px-4 py-2.5">
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
            className="lineup-model inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs"
            style={{
              borderColor: `${getModelColor(modelId)}40`,
              background: `${getModelColor(modelId)}15`,
              color: getModelColor(modelId),
            }}
            title={modelSpec.revision ? `${modelId}@${modelSpec.revision}` : modelId}
          >
            {modelId.split("/").pop()}
            {modelSpec.revision && (
              <span style={{ color: "var(--text-muted)", fontSize: 9 }}>
                @{modelSpec.revision.slice(0, 7)}
              </span>
            )}
            {transfer && (transfer.status === "downloading" || transfer.status === "loading") && (
              <span style={{ color: "var(--text-muted)", fontSize: 9 }}>
                {Math.round(transfer.progress * 100)}%
              </span>
            )}
            {transfer?.status === "error" && (
              <AlertTriangle size={10} style={{ color: "var(--error)" }} />
            )}
            {!lineupLocked && !sessionId && (
              <button onClick={() => removeModel(modelId)} className="hover:opacity-70" aria-label={`Remove ${modelId}`}>
                <X size={12} />
              </button>
            )}
          </span>
          );
        })}
        {!lineupLocked && selectedModels.length < 3 && (
          <div className="relative">
            <button
              onClick={() => setShowPicker((current) => !current)}
              className="lineup-add inline-flex items-center gap-1 rounded-full border border-dashed border-[var(--border-default)] px-2.5 py-1 text-xs text-[var(--text-muted)] transition-colors duration-[var(--duration-fast)] hover:border-[var(--border-strong)] hover:text-[var(--text-secondary)]"
            >
              <Plus size={12} /> Add model
            </button>
            {showPicker && (
              <div className="absolute left-0 top-full z-50 mt-1 min-w-[240px] overflow-hidden rounded-lg border border-[var(--border-default)] bg-[var(--bg-tertiary)] shadow-lg">
                {unselectedModels.length === 0 ? (
                  <div className="px-3 py-3 text-xs text-[var(--text-muted)]">No more models available</div>
                ) : (
                  unselectedModels.map((model) => (
                    <button
                      key={model.id}
                      onClick={() => addModel(model.id)}
                      disabled={checkingModelId !== null}
                      className="w-full px-3 py-2 text-left text-xs text-[var(--text-secondary)] transition-colors duration-[var(--duration-fast)] hover:bg-[var(--bg-surface)]"
                    >
                      <div className="flex items-center gap-1.5">
                        {checkingModelId === model.id && <Loader2 size={10} className="animate-spin" />}
                        {model.name || model.id.split("/").pop()}
                      </div>
                      <div className="mt-0.5 truncate text-[10px] text-[var(--text-muted)]">{model.id}</div>
                    </button>
                  ))
                )}
                {onBrowseModels && (
                  <button
                    onClick={handleBrowseModels}
                    className="flex w-full items-center gap-1.5 border-t border-[var(--border-subtle)] px-3 py-2 text-left text-xs text-[var(--accent)] hover:bg-[var(--bg-surface)]"
                  >
                    <Library size={12} /> Browse Hugging Face models
                  </button>
                )}
              </div>
            )}
          </div>
        )}
        {lineupLocked && (
          <span className="flex items-center gap-1 text-[10px] text-[var(--text-muted)]" title="The model lineup stays fixed for a fair thread history">
            <Lock size={10} /> fixed for this thread
          </span>
        )}
        <div className="flex-1" />
        <span className="compare-method">
          Local · sequential
        </span>
      </div>

      {error && (
        <div className="border-b border-red-500/20 bg-[var(--error-muted)] px-4 py-2 text-xs text-[var(--error)]">
          {error}
        </div>
      )}

      {lineupNotice && (
        <div className="border-b border-[var(--border-subtle)] bg-[var(--bg-secondary)] px-4 py-2 text-xs text-[var(--text-muted)]">
          {lineupNotice}
        </div>
      )}

      {installPending && (
        <div className="border-b border-[var(--border-subtle)] bg-[var(--bg-secondary)] px-4 py-2 text-xs text-[var(--text-muted)]">
          Installing the selected revision. You can run the comparison when every model is ready.
        </div>
      )}

      {/* Side-by-side transcript */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        {isLoadingThread && (
          <div className="flex flex-1 items-center justify-center text-sm text-[var(--text-muted)]">
            <Loader2 size={14} className="mr-2 animate-spin" /> Opening comparison…
          </div>
        )}

        {!isLoadingThread && panels.length === 0 && (
          <div className="comparison-setup">
            <div className="setup-header">
              <div>
                <h1>New comparison</h1>
                <p>Choose at least two models.</p>
              </div>
              <span>0 / 3</span>
            </div>
            <div className="model-slots">
              {[0, 1, 2].map((index) => (
                <button
                  key={index}
                  className="model-slot"
                  onClick={handleBrowseModels}
                  aria-label={`Choose model ${index + 1}`}
                  disabled={!onBrowseModels}
                >
                  <span className="slot-index">0{index + 1}</span>
                  <span className="slot-action"><Plus size={15} /> Choose model</span>
                  <span className="slot-note">{index < 2 ? "Required" : "Optional"}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {!isLoadingThread && panels.map((panel, idx) => (
          <div
            key={panel.modelId}
            className={`flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden ${idx > 0 ? "border-l border-[var(--border-subtle)]" : ""}`}
          >
            <div
              className="panel-header flex items-center gap-2 border-b border-[var(--border-subtle)] px-3 py-2"
              style={{ background: `${getModelColor(panel.modelId)}08` }}
            >
              <div className="h-2 w-2 rounded-full" style={{ background: getModelColor(panel.modelId) }} />
              <span className="truncate text-xs font-medium" style={{ color: getModelColor(panel.modelId) }} title={panel.modelId}>
                {panel.modelId.split("/").pop()}
              </span>
              <div className="flex-1" />
              {panel.status === "waiting" && <span className="text-[10px] text-[var(--text-muted)]">Waiting…</span>}
              {panel.status === "generating" && <Loader2 size={12} className="animate-spin text-[var(--accent)]" />}
              {panel.status === "done" && panel.timeMs !== undefined && (
                <span className="text-[10px] text-[var(--text-muted)]">
                  {(panel.timeMs / 1000).toFixed(1)}s · {panel.tokens ?? 0} tok
                </span>
              )}
            </div>

            <PanelTranscript panel={panel} />
          </div>
        ))}
      </div>

      <div className="mx-auto w-full max-w-4xl shrink-0">
        <ChatInput
          onSend={handleSend}
          disabled={isRunning || selectedModels.length < 2 || installPending || installFailed || wsState !== "open" || isLoadingThread}
          placeholder={
            installFailed
              ? "Fix the failed model install before running…"
              : installPending
                ? "Waiting for model installation…"
                : selectedModels.length < 2
              ? "Choose at least 2 models to begin…"
              : isRunning
                ? "Running the shared prompt…"
                : "Send the same prompt to every model…"
          }
        />
      </div>
    </div>
  );
}

function PanelTranscript({ panel }: { panel: PanelState }) {
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (transcript) {
      transcript.scrollTop = transcript.scrollHeight;
    }
  }, [panel.messages.length, panel.streamingContent]);

  return (
    <div ref={transcriptRef} className="min-h-0 flex-1 overflow-y-auto py-2">
      {panel.messages.length === 0 && !panel.streamingContent && (
        <div className="px-5 py-8 text-center text-xs text-[var(--text-muted)]">
          Ready for the first shared prompt
        </div>
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
    </div>
  );
}
