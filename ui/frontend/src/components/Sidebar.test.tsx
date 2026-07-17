import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "./Sidebar";
import type { Project, Session } from "../lib/types";

const { listSessions } = vi.hoisted(() => ({
  listSessions: vi.fn(),
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    sessions: { ...actual.sessions, list: listSessions },
  };
});

const project: Project = {
  id: "default",
  name: "Default",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  is_default: 1,
  session_count: 1,
  comparison_count: 1,
};

const comparison: Session = {
  id: "session-1",
  title: "Fast model comparison",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: new Date().toISOString(),
  is_compare: true,
  project_id: "default",
  models: ["org/model-one", "org/model-two"],
  comparison_models: [],
};

const baseProps = {
  currentView: "compare" as const,
  onViewChange: vi.fn(),
  activeSessionId: null,
  onSessionSelect: vi.fn(),
  onNewSession: vi.fn(),
  projects: [project],
  activeProjectId: "default",
  onProjectChange: vi.fn(),
  onProjectCreate: vi.fn(),
  collapsed: false,
  onToggleCollapse: vi.fn(),
};

describe("Sidebar history resilience", () => {
  beforeEach(() => listSessions.mockReset());

  it("keeps the last successful history visible when a refresh fails", async () => {
    listSessions
      .mockResolvedValueOnce([comparison])
      .mockResolvedValueOnce([])
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const { rerender } = render(<Sidebar {...baseProps} refreshKey={0} />);
    expect(await screen.findByText("Fast model comparison")).toBeVisible();

    rerender(<Sidebar {...baseProps} refreshKey={1} />);

    expect(await screen.findByText("Offline · showing saved history")).toBeVisible();
    expect(screen.getByText("Fast model comparison")).toBeVisible();
    expect(screen.queryByText("No comparisons yet")).not.toBeInTheDocument();
  });

  it("keeps successful-empty and failed-empty states distinct", async () => {
    listSessions.mockResolvedValueOnce([]).mockResolvedValueOnce([]);
    const { rerender } = render(<Sidebar {...baseProps} refreshKey={0} />);
    expect(await screen.findByText("No comparisons yet")).toBeVisible();

    listSessions
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    rerender(<Sidebar {...baseProps} refreshKey={1} />);

    expect(await screen.findByText("History unavailable")).toBeVisible();
    expect(screen.queryByText("No comparisons yet")).not.toBeInTheDocument();
  });

  it("labels running and failed comparison outcomes in text", async () => {
    listSessions.mockResolvedValueOnce([comparison]).mockResolvedValueOnce([]);
    const { rerender } = render(
      <Sidebar {...baseProps} sessionStates={{ "session-1": "running" }} />,
    );
    expect(await screen.findByText("Running…")).toBeVisible();

    rerender(<Sidebar {...baseProps} sessionStates={{ "session-1": "failed" }} />);
    await waitFor(() => expect(screen.getByText("Needs attention")).toBeVisible());
  });
});
