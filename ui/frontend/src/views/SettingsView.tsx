import { useState, useEffect, useRef } from "react";
import { Eye, EyeOff, Check, AlertCircle } from "lucide-react";
import { apiKeys as apiKeysApi } from "../lib/api";
import type { ApiKeyName, MaskedApiKeys } from "../lib/types";

interface ApiKey {
  key: string;
  envVar: ApiKeyName;
  label: string;
  description: string;
  placeholder: string;
}

const API_KEYS: ApiKey[] = [
  {
    key: "tavily",
    envVar: "TAVILY_API_KEY",
    label: "Tavily",
    description: "Powers web search. Get a key at tavily.com",
    placeholder: "tvly-...",
  },
  {
    key: "huggingface",
    envVar: "HF_TOKEN",
    label: "HuggingFace",
    description: "Required for gated models (Llama, etc). Get a token at huggingface.co/settings/tokens",
    placeholder: "hf_...",
  },
];

export function SettingsView() {
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [maskedKeys, setMaskedKeys] = useState<Record<string, string>>({});
  const [visibility, setVisibility] = useState<Record<string, boolean>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [revealing, setRevealing] = useState<Record<string, boolean>>({});
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const dirtyRef = useRef<Record<string, boolean>>({});

  useEffect(() => {
    let cancelled = false;
    apiKeysApi.list()
      .then((data: MaskedApiKeys) => {
        if (cancelled) return;
        setKeys(data);
        setMaskedKeys(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const setKeyDirty = (envVar: ApiKeyName, isDirty: boolean) => {
    dirtyRef.current[envVar] = isDirty;
    setDirty((current) => ({ ...current, [envVar]: isDirty }));
  };

  const handleChange = (envVar: ApiKeyName, value: string) => {
    setKeys((current) => ({ ...current, [envVar]: value }));
    setKeyDirty(envVar, true);
    setSaved((current) => ({ ...current, [envVar]: false }));
    setErrors((current) => ({ ...current, [envVar]: "" }));
  };

  const handleToggleVisibility = async (apiKey: ApiKey) => {
    const { key, envVar } = apiKey;
    if (visibility[key]) {
      setVisibility((current) => ({ ...current, [key]: false }));
      if (revealed[envVar] && !dirtyRef.current[envVar]) {
        setKeys((current) => ({
          ...current,
          [envVar]: maskedKeys[envVar] || "",
        }));
        setRevealed((current) => ({ ...current, [envVar]: false }));
      }
      return;
    }

    if (dirtyRef.current[envVar]) {
      setVisibility((current) => ({ ...current, [key]: true }));
      return;
    }

    setRevealing((current) => ({ ...current, [envVar]: true }));
    setErrors((current) => ({ ...current, [envVar]: "" }));
    try {
      const result = await apiKeysApi.reveal(envVar);
      if (dirtyRef.current[envVar]) return;
      setKeys((current) => ({ ...current, [envVar]: result.value }));
      setRevealed((current) => ({ ...current, [envVar]: true }));
      setVisibility((current) => ({ ...current, [key]: true }));
    } catch (error) {
      setErrors((current) => ({
        ...current,
        [envVar]: error instanceof Error ? error.message : "Failed to reveal",
      }));
    } finally {
      setRevealing((current) => ({ ...current, [envVar]: false }));
    }
  };

  const handleSave = async (envVar: ApiKeyName, value: string) => {
    try {
      const result = await apiKeysApi.save(envVar, value);
      setKeys((current) => ({ ...current, [envVar]: result.masked }));
      setMaskedKeys((current) => ({ ...current, [envVar]: result.masked }));
      setVisibility((current) => ({
        ...current,
        [API_KEYS.find((item) => item.envVar === envVar)?.key || envVar]: false,
      }));
      setRevealed((current) => ({ ...current, [envVar]: false }));
      setKeyDirty(envVar, false);
      setSaved((s) => ({ ...s, [envVar]: true }));
      setErrors((e) => ({ ...e, [envVar]: "" }));
      setTimeout(() => setSaved((s) => ({ ...s, [envVar]: false })), 2000);
    } catch (error) {
      setErrors((e) => ({
        ...e,
        [envVar]: error instanceof Error ? error.message : "Failed to save",
      }));
    }
  };

  return (
    <div className="settings-view" style={{ flex: 1, overflowY: "auto", padding: "32px 24px" }}>
      <div className="settings-inner" style={{ maxWidth: 560 }}>
        <h1 className="settings-title" style={{ fontSize: 18, fontWeight: 600, color: "var(--text-primary)", margin: "0 0 4px" }}>
          Settings
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-tertiary)", margin: "0 0 32px" }}>
          API keys are stored locally and never leave this device.
        </p>

        {/* API Keys */}
        <div style={{ marginBottom: 40 }}>
          <h2 style={{
            fontSize: 11,
            fontWeight: 500,
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            margin: "0 0 16px",
          }}>
            API Keys
          </h2>

          {API_KEYS.map((apiKey) => (
            <div
              key={apiKey.key}
              className="settings-card"
              style={{
                marginBottom: 20,
                padding: "16px",
                background: "var(--bg-secondary)",
                border: "1px solid var(--border-subtle)",
                borderRadius: 8,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>
                  {apiKey.label}
                </span>
                {saved[apiKey.envVar] && (
                  <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "var(--success)" }}>
                    <Check size={12} /> Saved
                  </span>
                )}
                {errors[apiKey.envVar] && (
                  <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "var(--error)" }}>
                    <AlertCircle size={12} /> {errors[apiKey.envVar]}
                  </span>
                )}
              </div>
              <p style={{ fontSize: 12, color: "var(--text-tertiary)", margin: "0 0 10px" }}>
                {apiKey.description}
              </p>
              <div style={{ display: "flex", gap: 8 }}>
                <div style={{ flex: 1, position: "relative" }}>
                  <input
                    type={visibility[apiKey.key] ? "text" : "password"}
                    value={keys[apiKey.envVar] || ""}
                    onChange={(e) => handleChange(apiKey.envVar, e.target.value)}
                    placeholder={apiKey.placeholder}
                    autoComplete="off"
                    style={{
                      width: "100%",
                      padding: "7px 36px 7px 10px",
                      background: "var(--bg-primary)",
                      border: "1px solid var(--border-default)",
                      borderRadius: 6,
                      color: "var(--text-primary)",
                      fontSize: 13,
                      fontFamily: "var(--font-mono)",
                      outline: "none",
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && dirty[apiKey.envVar]) {
                        handleSave(apiKey.envVar, keys[apiKey.envVar] || "");
                      }
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => handleToggleVisibility(apiKey)}
                    disabled={revealing[apiKey.envVar]}
                    aria-label={visibility[apiKey.key] ? `Hide ${apiKey.label} key` : `Show ${apiKey.label} key`}
                    aria-pressed={Boolean(visibility[apiKey.key])}
                    title={visibility[apiKey.key] ? "Hide key" : "Show key"}
                    style={{
                      position: "absolute",
                      right: 8,
                      top: "50%",
                      transform: "translateY(-50%)",
                      background: "none",
                      border: "none",
                      cursor: revealing[apiKey.envVar] ? "wait" : "pointer",
                      color: "var(--text-muted)",
                      padding: 2,
                      opacity: revealing[apiKey.envVar] ? 0.5 : 1,
                    }}
                  >
                    {visibility[apiKey.key] ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
                <button
                  type="button"
                  onClick={() => handleSave(apiKey.envVar, keys[apiKey.envVar] || "")}
                  disabled={!dirty[apiKey.envVar] || revealing[apiKey.envVar]}
                  style={{
                    padding: "7px 14px",
                    background: "var(--bg-surface)",
                    border: "1px solid var(--border-default)",
                    borderRadius: 6,
                    color: "var(--text-secondary)",
                    fontSize: 12,
                    fontWeight: 500,
                    cursor: dirty[apiKey.envVar] ? "pointer" : "default",
                    opacity: dirty[apiKey.envVar] ? 1 : 0.55,
                  }}
                >
                  Save
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* Info */}
        <div style={{
          fontSize: 11,
          color: "var(--text-muted)",
          borderTop: "1px solid var(--border-subtle)",
          paddingTop: 16,
        }}>
          Keys are written to <code style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            padding: "1px 4px",
            background: "var(--bg-elevated)",
            borderRadius: 3,
          }}>.env</code> in the project root. Changes take effect on the next tool call — no restart needed for Tavily. HuggingFace token changes require reloading the model.
        </div>
      </div>
    </div>
  );
}
