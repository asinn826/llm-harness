import { act, render, screen, waitFor } from "@testing-library/react";
import axe from "axe-core";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelsView } from "./ModelsView";

const { listModels, listUpdates, getPrefs, setHubSearch } = vi.hoisted(() => ({
  listModels: vi.fn(),
  listUpdates: vi.fn(),
  getPrefs: vi.fn(),
  setHubSearch: vi.fn(),
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    models: { ...actual.models, list: listModels, updates: listUpdates },
    prefs: { ...actual.prefs, get: getPrefs, setHubSearch },
  };
});

vi.mock("../contexts/DownloadsContext", () => ({
  useDownloads: () => ({ downloads: {}, subscribe: () => () => {} }),
}));

vi.mock("../components/ModelDetailsDrawer", () => ({
  ModelDetailsDrawer: ({ modelId }: { modelId: string }) => (
    <div role="dialog" aria-label={`Model details for ${modelId}`} />
  ),
}));

describe("model library states", () => {
  beforeEach(() => {
    listModels.mockResolvedValue({ recommended: [], cached: [], current: null, current_backend: null });
    listUpdates.mockResolvedValue([]);
    getPrefs.mockResolvedValue({ hub_search_enabled: false });
    setHubSearch.mockResolvedValue({ hub_search_enabled: true });
  });

  it("shows a successful empty state with a next action", async () => {
    const { container } = render(<ModelsView />);

    expect(await screen.findByRole("heading", { name: "No models in your library yet" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Browse Hugging Face" })).toBeVisible();
    expect(screen.queryByText("Model library unavailable")).not.toBeInTheDocument();

    const seriousViolations = (await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    })).violations.filter(
      (violation) => violation.impact === "serious" || violation.impact === "critical",
    );
    expect(seriousViolations).toEqual([]);
  });

  it("keeps an opt-in permission dialog explicit and cancel-first", async () => {
    const user = userEvent.setup();
    render(<ModelsView />);
    await screen.findByRole("heading", { name: "No models in your library yet" });

    await user.click(screen.getByRole("tab", { name: "Hub" }));
    const dialog = screen.getByRole("dialog", { name: "Search Hugging Face?" });
    expect(dialog).toHaveTextContent("Search terms are sent to huggingface.co");
    expect(dialog).toHaveTextContent("turn Hub search off later in Settings");
    expect(screen.getByRole("button", { name: "Allow Hub search" })).toBeVisible();

    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus());
  });

  it("opens model details from the full library row", async () => {
    const user = userEvent.setup();
    listModels.mockResolvedValue({
      recommended: [],
      cached: [{
        id: "Qwen/Qwen3.5-9B",
        name: "Qwen3.5-9B",
        author: "Qwen",
        backend: "hf",
        size_label: "18.0 GB",
        is_cached: true,
        is_loaded: false,
      }],
      current: null,
      current_backend: null,
    });

    render(<ModelsView />);

    await user.click(await screen.findByRole("button", {
      name: "Open details for Qwen/Qwen3.5-9B",
    }));

    expect(screen.getByRole("dialog", {
      name: "Model details for Qwen/Qwen3.5-9B",
    })).toBeVisible();
  });
});
