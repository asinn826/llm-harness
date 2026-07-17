import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, getErrorMessage, models } from "./api";

describe("API recovery messages", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("turns a network failure into an actionable offline error", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(models.list()).rejects.toMatchObject({
      name: "ApiError",
      kind: "offline",
      retryable: true,
      message: expect.stringContaining("local service is running"),
    });
  });

  it("does not expose an opaque 503 response", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(
      JSON.stringify({ detail: "upstream unavailable" }),
      { status: 503, headers: { "Content-Type": "application/json" } },
    ));

    await expect(models.list()).rejects.toMatchObject({
      kind: "server",
      retryable: true,
      message: "The Harness service is temporarily unavailable. Try again.",
    });
  });

  it("distinguishes an expired authorization from an offline service", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(
      JSON.stringify({ detail: "expired" }),
      { status: 401, headers: { "Content-Type": "application/json" } },
    ));

    await expect(models.list()).rejects.toMatchObject({
      kind: "unauthorized",
      retryable: false,
      message: "Your connection is no longer authorized. Reconnect and try again.",
    });
  });

  it("distinguishes a timeout from an immediate connection failure", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockImplementationOnce((_input, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));

    const assertion = expect(models.list()).rejects.toMatchObject({
      kind: "timeout",
      retryable: true,
      message: "Harness took too long to respond. Try again.",
    });
    await vi.advanceTimersByTimeAsync(15_000);
    await assertion;
    vi.useRealTimers();
  });

  it("keeps known API guidance when a view supplies a fallback", () => {
    const error = new ApiError("forbidden", "Harness doesn’t have permission to complete this action.");
    expect(getErrorMessage(error, "Generic fallback")).toBe(error.message);
  });
});
