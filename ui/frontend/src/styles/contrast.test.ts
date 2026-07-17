import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(process.cwd(), "src/index.css"), "utf8");

function declarations(selector: string): Record<string, string> {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const block = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))?.[1] ?? "";
  return Object.fromEntries(
    [...block.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map((match) => [match[1], match[2]]),
  );
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255);
  const linear = channels.map((channel) => (
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  ));
  return (0.2126 * linear[0]) + (0.7152 * linear[1]) + (0.0722 * linear[2]);
}

function contrast(foreground: string, background: string): number {
  const first = luminance(foreground);
  const second = luminance(background);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

describe("warm palette contrast", () => {
  it("keeps essential light-surface text tokens at WCAG AA contrast", () => {
    const tokens = declarations(":root");
    for (const name of [
      "text-primary",
      "text-secondary",
      "text-tertiary",
      "text-muted",
      "accent",
      "success",
      "warning",
      "error",
    ]) {
      expect(contrast(tokens[name], tokens["bg-primary"]), name).toBeGreaterThanOrEqual(4.5);
    }
    expect(contrast(tokens["accent-on-light"], tokens["accent-contrast"]), "primary action").toBeGreaterThanOrEqual(4.5);
  });

  it("keeps sidebar labels and accent cues legible on the dark surface", () => {
    const tokens = declarations(".app-sidebar");
    for (const name of ["text-primary", "text-secondary", "text-tertiary", "text-muted"]) {
      expect(contrast(tokens[name], tokens["bg-secondary"]), name).toBeGreaterThanOrEqual(4.5);
    }
    expect(contrast("#ee805b", tokens["bg-secondary"]), "dark-surface accent").toBeGreaterThanOrEqual(4.5);
    expect(contrast("#211813", "#ee805b"), "dark-surface primary action").toBeGreaterThanOrEqual(4.5);
  });
});
