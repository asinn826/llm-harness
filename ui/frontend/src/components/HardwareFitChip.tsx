/**
 * HardwareFitChip — Fits / Tight / Too big indicator.
 *
 * Heuristic:
 *   estimated_ram = size_bytes * (1.2 if quant="4-bit" else 2.0)
 *   Fits   if estimated_ram < 0.75 * total_ram
 *   Tight  if < 0.9 * total_ram
 *   Too big otherwise
 *
 * Hover (title attr) reveals the numerical breakdown. Not a hard filter —
 * power users sometimes override.
 */

import { useEffect, useState } from "react";
import { Cpu } from "lucide-react";
import { system as systemApi } from "../lib/api";
import type { HardwareInfo, ModelInfo } from "../lib/types";

type Verdict = "fits" | "tight" | "too_big" | "unknown";

let _hwCache: HardwareInfo | null = null;

export function HardwareFitChip({ model }: { model: ModelInfo }) {
  const [hw, setHw] = useState<HardwareInfo | null>(_hwCache);

  useEffect(() => {
    if (_hwCache) return;
    systemApi.hardware()
      .then((h) => { _hwCache = h; setHw(h); })
      .catch(() => {});
  }, []);

  const size = model.size_bytes ?? 0;
  if (!size || !hw) return null;

  const multiplier = (model.quantization || "").includes("4-bit") ? 1.2 : 2.0;
  const estRam = size * multiplier;

  let verdict: Verdict = "unknown";
  if (estRam < 0.75 * hw.total_memory_bytes) verdict = "fits";
  else if (estRam < 0.9 * hw.total_memory_bytes) verdict = "tight";
  else verdict = "too_big";

  const { label, color, bg } = verdictStyle(verdict);

  const title = [
    `Estimated RAM: ${formatBytes(estRam)} (${model.quantization || "fp16"})`,
    `This Mac: ${formatBytes(hw.total_memory_bytes)} total`,
    verdict === "fits"
      ? "Comfortable headroom for other apps."
      : verdict === "tight"
        ? "Will run but may swap under load."
        : "Won't run — exceeds memory.",
  ].join("\n");

  return (
    <span
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 3,
        fontSize: 10,
        padding: "1px 6px",
        borderRadius: 3,
        background: bg,
        color,
        fontWeight: 500,
        cursor: "help",
      }}
    >
      <Cpu size={10} /> {label}
    </span>
  );
}

function verdictStyle(v: Verdict): { label: string; color: string; bg: string } {
  switch (v) {
    case "fits":
      return { label: "Fits", color: "var(--success)", bg: "var(--success-muted)" };
    case "tight":
      return { label: "Tight", color: "var(--warning)", bg: "var(--warning-muted)" };
    case "too_big":
      return { label: "Too big", color: "var(--error)", bg: "var(--error-muted)" };
    default:
      return { label: "?", color: "var(--text-muted)", bg: "var(--bg-elevated)" };
  }
}

function formatBytes(n: number): string {
  if (n <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(1)} ${units[i]}`;
}
