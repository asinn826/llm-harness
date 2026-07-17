import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CompareView } from "./CompareView";

const { listModels, connect, send, socket } = vi.hoisted(() => ({
  listModels: vi.fn(),
  connect: vi.fn(),
  send: vi.fn(),
  socket: {
    onMessage: null as null | ((message: unknown) => void),
  },
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    models: { ...actual.models, list: listModels },
  };
});

vi.mock("../hooks/useWebSocket", () => ({
  useWebSocket: ({ onMessage }: { onMessage: (message: unknown) => void }) => {
    socket.onMessage = onMessage;
    return { send, connect, disconnect: vi.fn(), state: "open" };
  },
}));

vi.mock("../contexts/DownloadsContext", () => ({
  useDownloads: () => ({ downloads: {} }),
}));

describe("new comparison guidance", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    socket.onMessage = null;
    listModels.mockResolvedValue({ recommended: [], cached: [], current: null, current_backend: null });
  });

  it("keeps the empty state concise", async () => {
    const { container } = render(
      <CompareView
        sessionId={null}
        projectId="default"
        initialModels={[]}
        onDraftModelsChange={vi.fn()}
        onSessionCreated={vi.fn()}
        onSessionDetached={vi.fn()}
        onBrowseModels={vi.fn()}
      />,
    );

    expect(screen.getByText("Responses appear here.")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Comparison prompt" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Comparison prompt" })).toHaveAttribute(
      "placeholder",
      "Select two models above",
    );
    expect(screen.getAllByRole("button", { name: "Choose models" })).toHaveLength(1);
    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    await waitFor(() => expect(listModels).toHaveBeenCalled());

    const seriousViolations = (await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    })).violations.filter(
      (violation) => violation.impact === "serious" || violation.impact === "critical",
    );
    expect(seriousViolations).toEqual([]);
  });

  it("shows a model's tool call and result in its pane", async () => {
    render(
      <CompareView
        sessionId={null}
        projectId="default"
        initialModels={[{ model_id: "org/alpha" }, { model_id: "org/beta" }]}
        onDraftModelsChange={vi.fn()}
        onSessionCreated={vi.fn()}
        onSessionDetached={vi.fn()}
      />,
    );

    act(() => {
      socket.onMessage?.({
        type: "tool_call",
        session_id: "comparison-1",
        model_id: "org/alpha",
        index: 0,
        tool: "get_weather",
        args: { location: "Seattle" },
        needs_confirmation: false,
      });
      socket.onMessage?.({
        type: "tool_result",
        session_id: "comparison-1",
        model_id: "org/alpha",
        index: 0,
        tool: "get_weather",
        args: { location: "Seattle" },
        result: "Weather in Seattle: Clear, 70°F",
      });
    });

    const alphaPane = screen.getByRole("region", { name: "org/alpha response" });
    const toolTrace = within(alphaPane).getByRole("button", { name: /get_weather/ });
    expect(toolTrace).toHaveTextContent('location="Seattle"');
    fireEvent.click(toolTrace);
    expect(within(alphaPane).getByText("Weather in Seattle: Clear, 70°F")).toBeVisible();
    expect(within(screen.getByRole("region", { name: "org/beta response" })).queryByText("get_weather")).not.toBeInTheDocument();
  });

  it("routes approval for a mutating tool back to the comparison socket", () => {
    render(
      <CompareView
        sessionId={null}
        projectId="default"
        initialModels={[{ model_id: "org/alpha" }, { model_id: "org/beta" }]}
        onDraftModelsChange={vi.fn()}
        onSessionCreated={vi.fn()}
        onSessionDetached={vi.fn()}
      />,
    );

    act(() => {
      socket.onMessage?.({
        type: "tool_call",
        session_id: "comparison-1",
        model_id: "org/beta",
        index: 1,
        tool: "write_file",
        args: { path: "note.txt", content: "hello" },
        needs_confirmation: true,
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(send).toHaveBeenCalledWith({ type: "tool_response", approved: true });
  });
});
