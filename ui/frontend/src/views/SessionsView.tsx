import { useState, useEffect } from "react";
import {
  Search,
  Play,
  GitBranch,
  Download,
  Trash2,
  MessageSquare,
} from "lucide-react";
import { sessions as sessionsApi } from "../lib/api";
import { ChatMessage } from "../components/ChatMessage";
import type { Session, Message } from "../lib/types";
import { getModelColor } from "../lib/types";

interface SessionsViewProps {
  onResumeSession: (sessionId: string) => void;
}

export function SessionsView({ onResumeSession }: SessionsViewProps) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [search, setSearch] = useState("");

  useEffect(() => {
    sessionsApi.list(100).then(setSessions).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setMessages([]);
      return;
    }
    sessionsApi.messages(selectedId).then(setMessages).catch(() => {});
  }, [selectedId]);

  const handleSearch = async (query: string) => {
    setSearch(query);
    if (!query.trim()) {
      sessionsApi.list(100).then(setSessions);
      return;
    }
    try {
      const results = await sessionsApi.search(query);
      setSessions(results);
    } catch {
      // silently fail
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await sessionsApi.delete(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (selectedId === id) {
        setSelectedId(null);
        setMessages([]);
      }
    } catch {
      // silently fail
    }
  };

  const handleFork = async (id: string, position: number) => {
    try {
      const forked = await sessionsApi.fork(id, position);
      setSessions((prev) => [forked, ...prev]);
      setSelectedId(forked.id);
    } catch {
      // silently fail
    }
  };

  const handleExport = (format: "json" | "markdown") => {
    if (!selectedId) return;
    const session = sessions.find((s) => s.id === selectedId);
    if (!session) return;

    let content: string;
    let filename: string;
    let mimeType: string;

    if (format === "json") {
      content = JSON.stringify({ session, messages }, null, 2);
      filename = `${session.title.replace(/[^a-z0-9]/gi, "-")}.json`;
      mimeType = "application/json";
    } else {
      const lines = [`# ${session.title}\n`];
      for (const msg of messages) {
        if (msg.role === "user") lines.push(`**You:** ${msg.content}\n`);
        else if (msg.role === "assistant") lines.push(`**${msg.model_id || "Assistant"}:** ${msg.content}\n`);
        else if (msg.role === "tool") lines.push(`> \`${msg.tool_name}\`: ${msg.content.slice(0, 200)}${msg.content.length > 200 ? "..." : ""}\n`);
      }
      content = lines.join("\n");
      filename = `${session.title.replace(/[^a-z0-9]/gi, "-")}.md`;
      mimeType = "text/markdown";
    }

    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  // Group sessions by time
  const grouped = groupByTime(sessions);
  const selectedSession = sessions.find((s) => s.id === selectedId);

  return (
    <div className="flex-1 flex min-w-0">
      {/* Session list */}
      <div className="w-72 border-r border-[var(--border-subtle)] flex flex-col shrink-0">
        <div className="p-3 border-b border-[var(--border-subtle)]">
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input
              type="text"
              value={search}
              onChange={(e) => handleSearch(e.target.value)}
              placeholder="Search sessions..."
              className="w-full pl-8 pr-3 py-2 bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-md text-xs text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--accent)] transition-colors duration-[var(--duration-fast)]"
            />
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {Object.entries(grouped).map(([group, items]) => (
            <div key={group}>
              <div className="px-3 py-1.5 text-[9px] text-[var(--text-muted)] uppercase tracking-widest font-medium">
                {group}
              </div>
              {items.map((session) => (
                <button
                  key={session.id}
                  onClick={() => setSelectedId(session.id)}
                  className={`
                    w-full text-left px-3 py-2.5
                    transition-colors duration-[var(--duration-fast)]
                    ${selectedId === session.id
                      ? "bg-[var(--bg-elevated)] border-l-2 border-[var(--accent)]"
                      : "hover:bg-[var(--bg-surface)]"}
                  `}
                >
                  <div className="text-xs text-[var(--text-primary)] truncate leading-snug">
                    {session.title}
                  </div>
                  <div className="flex items-center gap-1.5 mt-1">
                    {session.models?.map((model) => (
                      <div
                        key={model}
                        className="w-1.5 h-1.5 rounded-full"
                        style={{ background: getModelColor(model) }}
                      />
                    ))}
                    <span className="text-[10px] text-[var(--text-muted)]">
                      {session.message_count || 0} msgs
                    </span>
                  </div>
                </button>
              ))}
            </div>
          ))}
          {sessions.length === 0 && (
            <div className="text-center py-12 text-xs text-[var(--text-muted)]">
              {search ? "No results" : "No sessions yet"}
            </div>
          )}
        </div>
      </div>

      {/* Detail panel */}
      <div className="flex-1 flex flex-col min-w-0">
        {!selectedSession ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center text-[var(--text-muted)]">
              <MessageSquare size={32} strokeWidth={1} className="mx-auto mb-2 opacity-30" />
              <div className="text-xs">Select a session to preview</div>
            </div>
          </div>
        ) : (
          <>
            {/* Detail header */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border-subtle)]">
              <h2 className="text-sm font-medium text-[var(--text-primary)] flex-1 truncate">
                {selectedSession.title}
              </h2>
              <div className="flex items-center gap-1.5 shrink-0">
                <button
                  onClick={() => onResumeSession(selectedSession.id)}
                  className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] transition-colors duration-[var(--duration-fast)]"
                >
                  <Play size={12} /> Resume
                </button>
                <button
                  onClick={() => handleFork(selectedSession.id, messages.length - 1)}
                  className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
                >
                  <GitBranch size={12} /> Fork
                </button>
                <button
                  onClick={() => handleExport("markdown")}
                  className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors duration-[var(--duration-fast)]"
                >
                  <Download size={12} /> Export
                </button>
                <button
                  onClick={() => handleDelete(selectedSession.id)}
                  className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-[var(--bg-elevated)] text-[var(--error)] hover:bg-[var(--error-muted)] transition-colors duration-[var(--duration-fast)]"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>

            {/* Stats bar */}
            <div className="flex items-center gap-4 px-4 py-2 border-b border-[var(--border-subtle)] text-[10px] text-[var(--text-muted)]">
              <span>{messages.length} turns</span>
              <span>·</span>
              <span>{messages.filter((m) => m.role === "tool").length} tool calls</span>
              <span>·</span>
              <span>
                ~{messages.reduce((sum, m) => sum + (m.tokens_generated || 0), 0)} tokens
              </span>
              <span>·</span>
              <span>{new Date(selectedSession.created_at).toLocaleString()}</span>
            </div>

            {/* Message preview */}
            <div className="flex-1 overflow-y-auto py-2">
              <div className="max-w-3xl mx-auto">
                {messages.map((msg) => (
                  <ChatMessage
                    key={msg.id}
                    role={msg.role}
                    content={msg.content}
                    modelId={msg.model_id}
                    toolName={msg.tool_name}
                    toolArgs={msg.tool_args}
                    tokensGenerated={msg.tokens_generated}
                    generationTimeMs={msg.generation_time_ms}
                  />
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function groupByTime(sessions: Session[]): Record<string, Session[]> {
  const groups: Record<string, Session[]> = {};
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86_400_000);
  const weekAgo = new Date(today.getTime() - 7 * 86_400_000);

  for (const s of sessions) {
    const date = new Date(s.updated_at);
    let group: string;
    if (date >= today) group = "Today";
    else if (date >= yesterday) group = "Yesterday";
    else if (date >= weekAgo) group = "This Week";
    else group = "Older";

    if (!groups[group]) groups[group] = [];
    groups[group].push(s);
  }

  return groups;
}
