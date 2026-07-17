import { useState, useRef, useEffect, useId } from "react";
import { ArrowUp } from "lucide-react";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  ariaLabel?: string;
}

export function ChatInput({
  onSend,
  disabled,
  placeholder = "Message...",
  description,
  actionLabel,
  onAction,
  ariaLabel = "Prompt",
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const descriptionId = useId();

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
    <div className="composer-shell">
      {description && (
        <div className="composer-guidance" id={descriptionId} role="status">
          <span>{description}</span>
          {actionLabel && onAction && (
            <button type="button" onClick={onAction}>{actionLabel}</button>
          )}
        </div>
      )}
      <div className="composer">
        <label className="sr-only" htmlFor={`${descriptionId}-input`}>{ariaLabel}</label>
        <textarea
          id={`${descriptionId}-input`}
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          aria-describedby={description ? descriptionId : undefined}
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
          type="button"
          onClick={handleSend}
          disabled={!value.trim() || disabled}
          aria-label="Run comparison"
          title="Run comparison"
          className={value.trim() && !disabled ? "send-btn-active" : ""}
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
            ...(!value.trim() || disabled ? {
              background: "var(--bg-elevated)",
              color: "var(--text-muted)",
            } : {}),
          }}
        >
          <ArrowUp size={16} strokeWidth={2} />
        </button>
      </div>
    </div>
  );
}
