import { X } from "lucide-react";
import { useState } from "react";

interface PermissionsBannerProps {
  missingAutomation: boolean;
  missingFullDisk: boolean;
  onRetry: () => void;
}

export function PermissionsBanner({ missingAutomation, missingFullDisk, onRetry }: PermissionsBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  const openAutomation = () => {
    fetch("/api/permissions/open-settings", { method: "POST" });
  };

  const openFullDisk = () => {
    fetch("/api/permissions/open-full-disk", { method: "POST" });
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "10px 16px",
        background: "var(--warning-muted)",
        borderBottom: "1px solid var(--border-subtle)",
        fontSize: 12,
        flexShrink: 0,
      }}
    >
      {missingFullDisk && (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ color: "var(--text-primary)", flex: 1 }}>
            Full Disk Access needed to detect iMessage vs SMS contacts.
            <span style={{ color: "var(--text-secondary)" }}>
              {" "}Without this, messages to SMS contacts may fail to deliver.
            </span>
          </span>
          <button onClick={openFullDisk} style={btnPrimary}>
            Grant Access
          </button>
        </div>
      )}
      {missingAutomation && (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ color: "var(--text-primary)", flex: 1 }}>
            Automation access needed for Messages and Contacts.
          </span>
          <button onClick={openAutomation} style={btnPrimary}>
            Open Settings
          </button>
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button onClick={onRetry} style={btnSecondary}>
          Check again
        </button>
        <button
          onClick={() => setDismissed(true)}
          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", padding: 2 }}
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}

const btnPrimary: React.CSSProperties = {
  padding: "4px 10px",
  background: "var(--accent)",
  border: "none",
  borderRadius: 4,
  color: "white",
  fontSize: 11,
  fontWeight: 500,
  cursor: "pointer",
  flexShrink: 0,
};

const btnSecondary: React.CSSProperties = {
  padding: "4px 10px",
  background: "var(--bg-surface)",
  border: "1px solid var(--border-default)",
  borderRadius: 4,
  color: "var(--text-secondary)",
  fontSize: 11,
  cursor: "pointer",
  flexShrink: 0,
};
