/** Stable identity for a transfer. JSON encoding avoids delimiter collisions. */
export function getTransferKey(
  modelId: string,
  backend: "mlx" | "hf" | null | undefined,
  revision: string | null | undefined = null,
): string {
  return JSON.stringify([modelId, backend ?? null, revision ?? null]);
}
