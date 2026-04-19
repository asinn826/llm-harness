import { useState, useEffect, useRef, useCallback } from "react";
import { ChatMessage, ToolCallApproval } from "../components/ChatMessage";
import { ChatInput } from "../components/ChatInput";
import { useWebSocket } from "../hooks/useWebSocket";
import { sessions as sessionsApi } from "../lib/api";
import type { Message, WSServerMessage } from "../lib/types";

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
  currentModelId: string | null;
}

export function ChatView({ sessionId, onSessionCreated, currentModelId }: ChatViewProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [pendingToolCall, setPendingToolCall] = useState<PendingToolCall | null>(null);
  const [streamingContent, setStreamingContent] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const streamingRef = useRef("");

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

        case "token":
          streamingRef.current += msg.data;
          setStreamingContent(streamingRef.current);
          break;

        case "tool_call":
          // Finalize streaming content as assistant message
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
          // Use streaming content if we have it, otherwise use the
          // response from the server (covers cases where tokens streamed
          // but were consumed by tool-call parsing on the server side)
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
    [onSessionCreated, currentModelId]
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

  return (
    <div className="flex flex-col flex-1 min-w-0">
      {/* Messages area */}
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 && !isGenerating && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <div className="text-[var(--text-tertiary)] text-sm mb-1">
                {currentModelId
                  ? `Ready — ${currentModelId.split("/").pop()}`
                  : "Load a model to start"}
              </div>
              <div className="text-[var(--text-muted)] text-xs">
                {currentModelId
                  ? "Send a message to start a conversation"
                  : "Use the model switcher in the sidebar"}
              </div>
            </div>
          </div>
        )}

        <div className="py-4 px-6">
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

          {/* Streaming assistant message */}
          {streamingContent && (
            <ChatMessage
              role="assistant"
              content={streamingContent}
              modelId={currentModelId}
              isStreaming
            />
          )}

          {/* Tool call approval */}
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
      </div>

      {/* Input */}
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
