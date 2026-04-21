/**
 * UpdateBadge — small "Update available" pill for Library cards.
 *
 * Shown when either:
 *  - the cached commit SHA differs from the Hub's HEAD (exact-repo update), or
 *  - a curated superseder is cached (the newer family member is available).
 */

import { ArrowUpCircle } from "lucide-react";

interface UpdateBadgeProps {
  kind: "commit" | "superseded";
  /** Hover tooltip detail (e.g. "Qwen 3.5 4B is newer than your cached 3.4 4B") */
  title?: string;
  onClick?: () => void;
}

export function UpdateBadge({ kind, title, onClick }: UpdateBadgeProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 10,
        padding: "2px 7px",
        borderRadius: 10,
        background: "rgba(80, 136, 247, 0.15)",
        color: "var(--accent)",
        fontWeight: 500,
        border: "none",
        cursor: onClick ? "pointer" : "default",
      }}
    >
      <ArrowUpCircle size={10} />
      {kind === "commit" ? "Update" : "Newer available"}
    </button>
  );
}
