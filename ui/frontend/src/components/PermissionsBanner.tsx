import { X } from "lucide-react";
import { useState } from "react";

interface PermissionsBannerProps {
  onRetry: () => void;
}

export function PermissionsBanner({ onRetry }: PermissionsBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  const openSettings = () => {
    fetch("/api/permissions/open-settings", { method: "POST" });
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "8px 16px",
        background: "var(--warning-muted)",
        borderBottom: "1px solid var(--border-subtle)",
        fontSize: 12,
        flexShrink: 0,
      }}
    >
      <span style={{ color: "var(--text-primary)", flex: 1 }}>
        Grant access to Messages and Contacts to send texts and read your calendar.
      </span>
      <button
        onClick={openSettings}
        style={{
          padding: "4px 10px",
          background: "var(--accent)",
          border: "none",
          borderRadius: 4,
          color: "white",
          fontSize: 11,
          fontWeight: 500,
          cursor: "pointer",
          flexShrink: 0,
        }}
      >
        Open Settings
      </button>
      <button
        onClick={onRetry}
        style={{
          padding: "4px 10px",
          background: "var(--bg-surface)",
          border: "1px solid var(--border-default)",
          borderRadius: 4,
          color: "var(--text-secondary)",
          fontSize: 11,
          cursor: "pointer",
          flexShrink: 0,
        }}
      >
        Check again
      </button>
      <button
        onClick={() => setDismissed(true)}
        style={{
          background: "none",
          border: "none",
          cursor: "pointer",
          color: "var(--text-muted)",
          padding: 2,
          flexShrink: 0,
        }}
      >
        <X size={14} />
      </button>
    </div>
  );
}
