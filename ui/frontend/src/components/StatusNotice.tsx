import { AlertCircle, CircleCheck, Info, RefreshCw, WifiOff } from "lucide-react";

type NoticeTone = "error" | "offline" | "info" | "success";

interface StatusNoticeProps {
  tone?: NoticeTone;
  title: string;
  message?: string;
  actionLabel?: string;
  onAction?: () => void;
  compact?: boolean;
}

const ICONS = {
  error: AlertCircle,
  offline: WifiOff,
  info: Info,
  success: CircleCheck,
};

export function StatusNotice({
  tone = "info",
  title,
  message,
  actionLabel,
  onAction,
  compact = false,
}: StatusNoticeProps) {
  const Icon = ICONS[tone];
  const role = tone === "error" || tone === "offline" ? "alert" : "status";

  return (
    <div className={`status-notice status-notice-${tone}${compact ? " status-notice-compact" : ""}`} role={role}>
      <Icon size={compact ? 14 : 16} aria-hidden="true" />
      <div className="status-notice-copy">
        <strong>{title}</strong>
        {message && <span>{message}</span>}
      </div>
      {actionLabel && onAction && (
        <button type="button" onClick={onAction}>
          <RefreshCw size={13} aria-hidden="true" />
          {actionLabel}
        </button>
      )}
    </div>
  );
}
