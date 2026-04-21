import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { AlertCircle, Download } from "lucide-react";
import { ChatMessage, ToolCallApproval } from "../components/ChatMessage";
import { ChatInput } from "../components/ChatInput";
import { useWebSocket } from "../hooks/useWebSocket";
import { sessions as sessionsApi, models as modelsApi } from "../lib/api";
import type { Message, WSServerMessage, ModelInfo } from "../lib/types";
import { useDownloads } from "../contexts/DownloadsContext";

interface DisplayMessage {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  modelId?: string | null;
  toolName?: string | null;
  toolArgs?: Record<string, unknown> | null;
  tokensGenerated?: number | null;
  generationTimeMs?: number | null;
  isStreaming?: boolean;
}

interface PendingToolCall {
  tool: string;
  args: Record<string, unknown>;
}

interface ChatViewProps {
  sessionId: string | null;
  onSessionCreated: (id: string) => void;
  onTitleUpdated?: (sessionId: string, title: string) => void;
  currentModelId: string | null;
}

export function ChatView({ sessionId, onSessionCreated, onTitleUpdated, currentModelId }: ChatViewProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [pendingToolCall, setPendingToolCall] = useState<PendingToolCall | null>(null);
  const [streamingContent, setStreamingContent] = useState("");
  const [availableModelIds, setAvailableModelIds] = useState<Set<string>>(new Set());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const streamingRef = useRef("");

  const { startDownload } = useDownloads();

  // Fetch the list of available model IDs to detect deleted-model sessions
  useEffect(() => {
    modelsApi.list().then((data) => {
      const ids = new Set<string>();
      data.recommended.forEach((m) => { if (m.is_cached) ids.add(m.id); });
      data.cached.forEach((m) => ids.add(m.id));
      setAvailableModelIds(ids);
    }).catch(() => {});
  }, [sessionId, currentModelId]);

  // Find the session's most recent assistant model_id
  const sessionModelId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.role === "assistant" && m.modelId) return m.modelId;
    }
    return null;
  }, [messages]);

  // Banner condition: session has a model_id, but it's not available and
  // we're not already using it (defensive: only show if we've actually
  // fetched the model list, i.e. the set has entries).
  const showDeletedBanner = sessionModelId
    && availableModelIds.size > 0
    && !availableModelIds.has(sessionModelId)
    && currentModelId !== sessionModelId;

  // Load messages for existing session
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      return;
    }
    sessionsApi.messages(sessionId).then((msgs) => {
      setMessages(
        msgs.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          modelId: m.model_id,
          toolName: m.tool_name,
          toolArgs: m.tool_args,
          tokensGenerated: m.tokens_generated,
          generationTimeMs: m.generation_time_ms,
        }))
      );
    });
  }, [sessionId]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  const handleWsMessage = useCallback(
    (msg: WSServerMessage) => {
      switch (msg.type) {
        case "session_created":
          onSessionCreated(msg.session_id);
          break;

        case "title_updated":
          onTitleUpdated?.(msg.session_id, msg.title);
          break;

        case "token":
          streamingRef.current += msg.data;
          setStreamingContent(streamingRef.current);
          break;

        case "tool_call":
          if (streamingRef.current) {
            setMessages((prev) => [
              ...prev,
              {
                id: `stream-${Date.now()}`,
                role: "assistant",
                content: streamingRef.current,
                modelId: currentModelId,
              },
            ]);
            streamingRef.current = "";
            setStreamingContent("");
          }

          if (msg.needs_confirmation) {
            setPendingToolCall({ tool: msg.tool, args: msg.args });
          }
          break;

        case "tool_result":
          setPendingToolCall(null);
          setMessages((prev) => [
            ...prev,
            {
              id: `tool-${Date.now()}`,
              role: "tool",
              content: msg.result,
              toolName: msg.tool,
              toolArgs: msg.args,
            },
          ]);
          break;

        case "done": {
          const finalContent = streamingRef.current || ("response" in msg ? msg.response : "") || "";
          if (finalContent) {
            setMessages((prev) => [
              ...prev,
              {
                id: `done-${Date.now()}`,
                role: "assistant",
                content: finalContent,
                modelId: currentModelId,
                tokensGenerated: msg.tokens,
                generationTimeMs: msg.time_ms,
              },
            ]);
          }
          streamingRef.current = "";
          setStreamingContent("");
          setIsGenerating(false);
          break;
        }

        case "error":
          setIsGenerating(false);
          streamingRef.current = "";
          setStreamingContent("");
          setMessages((prev) => [
            ...prev,
            {
              id: `error-${Date.now()}`,
              role: "assistant",
              content: `Error: ${msg.message}`,
            },
          ]);
          break;
      }
    },
    [onSessionCreated, onTitleUpdated, currentModelId]
  );

  const { send, state: wsState } = useWebSocket({
    path: "/ws/chat",
    onMessage: handleWsMessage,
  });

  const handleSend = (content: string) => {
    setMessages((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, role: "user", content },
    ]);
    setIsGenerating(true);
    streamingRef.current = "";
    setStreamingContent("");

    send({
      type: "message",
      content,
      session_id: sessionId || undefined,
      model_id: currentModelId || undefined,
    });
  };

  const handleToolApprove = () => {
    send({ type: "tool_response", approved: true });
    setPendingToolCall(null);
  };

  const handleToolDeny = () => {
    send({ type: "tool_response", approved: false });
    setPendingToolCall(null);
  };

  const hasMessages = messages.length > 0 || isGenerating;

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minWidth: 0, height: "100%" }}>
      {/* Deleted-model banner */}
      {showDeletedBanner && sessionModelId && (
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "10px 20px",
          background: "var(--warning-muted)",
          borderBottom: "1px solid var(--border-subtle)",
          fontSize: 12,
          flexShrink: 0,
        }}>
          <AlertCircle size={14} style={{ color: "var(--warning)", flexShrink: 0 }} />
          <span style={{ flex: 1, color: "var(--text-secondary)" }}>
            <strong style={{ color: "var(--text-primary)" }}>{sessionModelId.split("/").pop()}</strong> was removed from cache. Transcript is read-only.
          </span>
          <button
            onClick={() => startDownload(sessionModelId, "mlx")}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "4px 10px",
              background: "var(--accent)",
              color: "white",
              border: "none",
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 500,
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            <Download size={11} /> Redownload
          </button>
        </div>
      )}

      {/* Scrollable messages */}
      <div style={{ flex: 1, overflowY: "auto" }}>
        {!hasMessages && (
          <div style={{ padding: "24px", paddingTop: "40vh" }}>
            <div style={{ color: "var(--text-tertiary)", fontSize: 14, marginBottom: 4 }}>
              {currentModelId
                ? `Ready — ${currentModelId.split("/").pop()}`
                : "Load a model to start"}
            </div>
            <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
              {currentModelId
                ? "Send a message to start a conversation"
                : "Use the model switcher in the sidebar"}
            </div>
          </div>
        )}

        {hasMessages && (
          <div style={{ padding: "16px 24px" }}>
            {messages.map((msg) => (
              <ChatMessage
                key={msg.id}
                role={msg.role}
                content={msg.content}
                modelId={msg.modelId}
                toolName={msg.toolName}
                toolArgs={msg.toolArgs}
                tokensGenerated={msg.tokensGenerated}
                generationTimeMs={msg.generationTimeMs}
              />
            ))}

            {isGenerating && (
              <ChatMessage
                role="assistant"
                content={streamingContent}
                modelId={currentModelId}
                isStreaming
              />
            )}

            {pendingToolCall && (
              <ToolCallApproval
                toolName={pendingToolCall.tool}
                args={pendingToolCall.args}
                onApprove={handleToolApprove}
                onDeny={handleToolDeny}
              />
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input bar — pinned to bottom */}
      <ChatInput
        onSend={handleSend}
        disabled={isGenerating || wsState !== "open"}
        placeholder={
          wsState !== "open"
            ? "Connecting..."
            : isGenerating
              ? "Generating..."
              : "Message..."
        }
      />
    </div>
  );
}
