import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { ChevronDown, ChevronRight, Terminal, AlertCircle } from "lucide-react";
import { getModelColor } from "../lib/types";

/** Strip think blocks from model output (client-side safety net).
 *  Handles three cases:
 *  1. Full block: <think>...</think>
 *  2. Missing opening tag (server stripped it): everything up to </think>
 *  3. Unclosed block (still streaming): <think>... with no closing tag
 */
function stripThink(text: string): string {
  // Full <think>...</think> blocks
  let cleaned = text.replace(/<think>[\s\S]*?<\/think>\s*/g, "");
  // Missing opening tag — strip everything before and including </think>
  cleaned = cleaned.replace(/^[\s\S]*?<\/think>\s*/g, "");
  // Unclosed <think> block (streaming, no closing tag yet)
  cleaned = cleaned.replace(/<think>[\s\S]*$/, "");
  return cleaned.trim();
}

/** Fix markdown tables that are all on one line.
 *  Models sometimes output: | A | B | | --- | --- | | 1 | 2 |
 *  ReactMarkdown needs each row on its own line.
 */
function fixMarkdownTables(text: string): string {
  // Match sequences of | ... | that look like table rows
  return text.replace(/(\|[^|\n]+\|)\s*(?=\|)/g, "$1\n");
}

interface ChatMessageProps {
  role: "user" | "assistant" | "tool";
  content: string;
  modelId?: string | null;
  toolName?: string | null;
  toolArgs?: Record<string, unknown> | null;
  tokensGenerated?: number | null;
  generationTimeMs?: number | null;
  isStreaming?: boolean;
}

export function ChatMessage({
  role,
  content,
  modelId,
  toolName,
  toolArgs,
  tokensGenerated,
  generationTimeMs,
  isStreaming,
}: ChatMessageProps) {
  if (role === "tool") {
    return <ToolResultMessage content={content} toolName={toolName} toolArgs={toolArgs} />;
  }

  if (role === "user") {
    return (
      <div className="px-5 py-3">
        <div className="text-[10px] text-[var(--text-muted)] mb-1 font-medium uppercase tracking-wider">
          You
        </div>
        <div className="text-[var(--text-primary)] text-sm leading-relaxed">
          {content}
        </div>
      </div>
    );
  }

  // Assistant — strip leaked think tags and fix table formatting
  const displayContent = fixMarkdownTables(stripThink(content));
  const modelColor = modelId ? getModelColor(modelId) : "var(--text-muted)";
  const modelDisplay = modelId?.split("/").pop() || "Assistant";

  return (
    <div className="px-5 py-3">
      <div className="flex items-center gap-1.5 mb-1">
        <div className="w-1.5 h-1.5 rounded-full" style={{ background: modelColor }} />
        <span className="text-[10px] text-[var(--text-muted)] font-medium uppercase tracking-wider">
          {modelDisplay}
        </span>
        {tokensGenerated && generationTimeMs && (
          <span className="text-[10px] text-[var(--text-muted)] ml-auto">
            {(generationTimeMs / 1000).toFixed(1)}s · {tokensGenerated} tok
          </span>
        )}
      </div>
      <div className="text-[var(--text-primary)] text-sm leading-relaxed prose prose-invert prose-sm max-w-none">
        {displayContent ? (
          <>
            <ReactMarkdown
              components={{
                code: ({ children, className }) => {
                  const isInline = !className;
                  if (isInline) {
                    return (
                      <code className="px-1 py-0.5 rounded bg-[var(--bg-elevated)] text-[var(--accent)] text-xs font-[var(--font-mono)]">
                        {children}
                      </code>
                    );
                  }
                  return (
                    <pre className="bg-[var(--bg-primary)] border border-[var(--border-subtle)] rounded-md p-3 overflow-x-auto my-2">
                      <code className="text-xs font-[var(--font-mono)] text-[var(--text-secondary)]">
                        {children}
                      </code>
                    </pre>
                  );
                },
                table: ({ children }) => (
                  <div className="overflow-x-auto my-2">
                    <table className="text-xs border-collapse w-full">
                      {children}
                    </table>
                  </div>
                ),
                thead: ({ children }) => (
                  <thead className="border-b border-[var(--border-default)]">{children}</thead>
                ),
                th: ({ children }) => (
                  <th className="text-left px-3 py-1.5 text-[var(--text-secondary)] font-medium">{children}</th>
                ),
                td: ({ children }) => (
                  <td className="px-3 py-1.5 text-[var(--text-primary)] border-b border-[var(--border-subtle)]">{children}</td>
                ),
              }}
            >
              {displayContent}
            </ReactMarkdown>
            {isStreaming && (
              <span
                className="inline-block w-1.5 h-4 rounded-sm ml-0.5 align-text-bottom"
                style={{
                  background: modelColor,
                  animation: "think-wave 1.4s ease-in-out infinite",
                }}
              />
            )}
          </>
        ) : isStreaming || (!displayContent && content) ? (
          /* Show thinking dots when: streaming with no content yet,
             OR content exists but is all inside a think block (stripped to empty) */
          <div className="thinking-dots">
            <span style={{ background: modelColor }} />
            <span style={{ background: modelColor }} />
            <span style={{ background: modelColor }} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ToolResultMessage({
  content,
  toolName,
  toolArgs,
}: {
  content: string;
  toolName?: string | null;
  toolArgs?: Record<string, unknown> | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const isLong = content.length > 300;
  const isError = content.startsWith("Error");
  const displayContent = isLong && !expanded ? content.slice(0, 300) + "..." : content;

  return (
    <div className="px-5 py-1.5">
      <div
        className={`
          rounded-md border text-xs font-[var(--font-mono)]
          ${isError
            ? "bg-[var(--error-muted)] border-red-500/20"
            : "bg-[var(--bg-primary)] border-[var(--border-subtle)]"}
        `}
      >
        {/* Header */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center gap-2 px-3 py-2 hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
        >
          {isError ? (
            <AlertCircle size={12} className="text-[var(--error)] shrink-0" />
          ) : (
            <Terminal size={12} className="text-[var(--text-tertiary)] shrink-0" />
          )}
          <span className="text-[var(--text-secondary)]">{toolName || "tool"}</span>
          {toolArgs && (
            <span className="text-[var(--text-muted)] truncate">
              ({Object.entries(toolArgs).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})
            </span>
          )}
          <span className="ml-auto shrink-0">
            {expanded ? (
              <ChevronDown size={12} className="text-[var(--text-muted)]" />
            ) : (
              <ChevronRight size={12} className="text-[var(--text-muted)]" />
            )}
          </span>
        </button>

        {/* Content */}
        {expanded && (
          <div className="px-3 pb-2 border-t border-[var(--border-subtle)]">
            <pre className="whitespace-pre-wrap text-[var(--text-secondary)] text-[11px] leading-relaxed mt-2 overflow-x-auto">
              {displayContent}
            </pre>
            {isLong && !expanded && (
              <button
                onClick={() => setExpanded(true)}
                className="text-[var(--accent)] text-[10px] mt-1 hover:underline"
              >
                Show all ({content.length} chars)
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** Pending tool call that needs user approval */
export function ToolCallApproval({
  toolName,
  args,
  onApprove,
  onDeny,
}: {
  toolName: string;
  args: Record<string, unknown>;
  onApprove: () => void;
  onDeny: () => void;
}) {
  // Auto-focus approve button so Enter works immediately
  const approveRef = useRef<HTMLButtonElement>(null);
  useState(() => {
    setTimeout(() => approveRef.current?.focus(), 50);
  });

  // Global Enter key handler
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        onApprove();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onApprove]);

  return (
    <div className="px-5 py-2">
      <div className="rounded-md border border-[var(--warning)]/30 bg-[var(--warning-muted)] p-3">
        <div className="flex items-center gap-2 mb-2">
          <Terminal size={14} className="text-[var(--warning)]" />
          <span className="text-sm font-medium text-[var(--text-primary)]">
            {toolName}
          </span>
          <span className="text-xs text-[var(--text-muted)]">requires approval</span>
        </div>
        <pre className="text-xs text-[var(--text-secondary)] font-[var(--font-mono)] mb-3 overflow-x-auto">
          {JSON.stringify(args, null, 2)}
        </pre>
        <div className="flex items-center gap-2">
          <button
            ref={approveRef}
            onClick={onApprove}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] transition-colors duration-[var(--duration-fast)]"
          >
            Approve
          </button>
          <button
            onClick={onDeny}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
          >
            Deny
          </button>
          <span className="text-[10px] text-[var(--text-muted)] ml-1">
            press Enter to approve
          </span>
        </div>
      </div>
    </div>
  );
}
