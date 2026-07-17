import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SettingsView } from "./SettingsView";

const { listKeys, saveKey, revealKey, getPrefs, setHubSearch } = vi.hoisted(() => ({
  listKeys: vi.fn(),
  saveKey: vi.fn(),
  revealKey: vi.fn(),
  getPrefs: vi.fn(),
  setHubSearch: vi.fn(),
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    apiKeys: { list: listKeys, save: saveKey, reveal: revealKey },
    prefs: { ...actual.prefs, get: getPrefs, setHubSearch },
  };
});

describe("settings feedback", () => {
  beforeEach(() => {
    listKeys.mockResolvedValue({ TAVILY_API_KEY: "", HF_TOKEN: "" });
    getPrefs.mockResolvedValue({ hub_search_enabled: false });
    saveKey.mockResolvedValue({ status: "saved", unchanged: false, masked: "hf_••••last" });
  });

  it("shows dirty, saving, saved, and model-reload states for an HF token", async () => {
    const user = userEvent.setup();
    const onReloadModels = vi.fn();
    render(<SettingsView onReloadModels={onReloadModels} />);

    const input = await screen.findByLabelText("Hugging Face API key");
    await user.type(input, "hf_abcdefghijk");
    expect(screen.getByText("Unsaved changes")).toBeVisible();

    await user.click(screen.getAllByRole("button", { name: "Save" })[1]);
    expect(await screen.findByText("Saved")).toBeVisible();
    expect(screen.getByText("Hugging Face token updated")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Reload models" }));
    expect(onReloadModels).toHaveBeenCalledOnce();
  });

  it("validates an invalid token before sending it", async () => {
    const user = userEvent.setup();
    render(<SettingsView />);
    const input = await screen.findByLabelText("Hugging Face API key");
    await user.type(input, "wrong-token");
    await user.click(screen.getAllByRole("button", { name: "Save" })[1]);

    expect(screen.getByText("Hugging Face tokens should start with hf_.")).toBeVisible();
    expect(saveKey).not.toHaveBeenCalled();
  });
});
