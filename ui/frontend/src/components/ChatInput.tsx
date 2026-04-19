import { useState, useRef, useEffect } from "react";
import { ArrowUp } from "lucide-react";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function ChatInput({ onSend, disabled, placeholder = "Message..." }: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = "auto";
      ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
    }
  }, [value]);

  return (
    <div style={{ padding: "12px 24px", borderTop: "1px solid var(--border-subtle)", width: "100%" }}>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          gap: 8,
          background: "var(--bg-surface)",
          borderRadius: 8,
          border: "1px solid var(--border-subtle)",
          padding: "8px 12px",
          width: "100%",
        }}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          style={{
            flex: 1,
            background: "transparent",
            fontSize: 14,
            color: "var(--text-primary)",
            resize: "none",
            outline: "none",
            border: "none",
            minHeight: 24,
            maxHeight: 200,
            lineHeight: 1.5,
            fontFamily: "inherit",
          }}
        />
        <button
          onClick={handleSend}
          disabled={!value.trim() || disabled}
          style={{
            width: 28,
            height: 28,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 6,
            border: "none",
            cursor: value.trim() && !disabled ? "pointer" : "default",
            flexShrink: 0,
            background: value.trim() && !disabled ? "var(--accent)" : "var(--bg-elevated)",
            color: value.trim() && !disabled ? "white" : "var(--text-muted)",
          }}
        >
          <ArrowUp size={16} strokeWidth={2} />
        </button>
      </div>
    </div>
  );
}
