import { useState, useEffect, useRef, useCallback } from "react";
import { Eye, EyeOff, Check, AlertCircle, Loader2, RefreshCw } from "lucide-react";
import { apiKeys as apiKeysApi, getErrorMessage, prefs as prefsApi } from "../lib/api";
import type { ApiKeyName, MaskedApiKeys } from "../lib/types";
import { StatusNotice } from "../components/StatusNotice";

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
    description: "Web search · tavily.com",
    placeholder: "tvly-...",
  },
  {
    key: "huggingface",
    envVar: "HF_TOKEN",
    label: "Hugging Face",
    description: "Gated models · huggingface.co/settings/tokens",
    placeholder: "hf_...",
  },
];

interface SettingsViewProps {
  onReloadModels?: () => void;
}

function validateKey(apiKey: ApiKey, value: string): string | null {
  if (!value || value.includes("•")) return null;
  if (/\s/.test(value)) return `${apiKey.label} keys cannot contain spaces.`;
  if (value.length < 8) return `${apiKey.label} keys appear to be too short.`;
  if (apiKey.envVar === "HF_TOKEN" && !value.startsWith("hf_")) {
    return "Hugging Face tokens should start with hf_.";
  }
  if (apiKey.envVar === "TAVILY_API_KEY" && !value.startsWith("tvly-")) {
    return "Tavily keys should start with tvly-.";
  }
  return null;
}

export function SettingsView({ onReloadModels }: SettingsViewProps) {
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [maskedKeys, setMaskedKeys] = useState<Record<string, string>>({});
  const [visibility, setVisibility] = useState<Record<string, boolean>>({});
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [revealing, setRevealing] = useState<Record<string, boolean>>({});
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadNeeded, setReloadNeeded] = useState(false);
  const [hubSearchEnabled, setHubSearchEnabled] = useState(false);
  const [hubSaving, setHubSaving] = useState(false);
  const [hubError, setHubError] = useState<string | null>(null);
  const dirtyRef = useRef<Record<string, boolean>>({});

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    const [keysResult, prefsResult] = await Promise.allSettled([
      apiKeysApi.list(),
      prefsApi.get(),
    ]);
    if (keysResult.status === "fulfilled") {
      const data: MaskedApiKeys = keysResult.value;
      setKeys(data);
      setMaskedKeys(data);
    }
    if (prefsResult.status === "fulfilled") {
      setHubSearchEnabled(prefsResult.value.hub_search_enabled);
    }
    const failure = keysResult.status === "rejected"
      ? keysResult.reason
      : prefsResult.status === "rejected"
        ? prefsResult.reason
        : null;
    if (failure) setLoadError(getErrorMessage(failure, "Couldn’t load settings."));
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

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
        [envVar]: getErrorMessage(error, "Could not reveal this key."),
      }));
    } finally {
      setRevealing((current) => ({ ...current, [envVar]: false }));
    }
  };

  const handleSave = async (apiKey: ApiKey, value: string) => {
    const { envVar } = apiKey;
    const validationError = validateKey(apiKey, value);
    if (validationError) {
      setErrors((current) => ({ ...current, [envVar]: validationError }));
      return;
    }
    setSaving((current) => ({ ...current, [envVar]: true }));
    setErrors((current) => ({ ...current, [envVar]: "" }));
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
      if (envVar === "HF_TOKEN" && !result.unchanged) setReloadNeeded(true);
      setTimeout(() => setSaved((s) => ({ ...s, [envVar]: false })), 2000);
    } catch (error) {
      setErrors((e) => ({
        ...e,
        [envVar]: getErrorMessage(error, `Couldn’t save the ${apiKey.label} key.`),
      }));
    } finally {
      setSaving((current) => ({ ...current, [envVar]: false }));
    }
  };

  const handleHubSearchToggle = async () => {
    const next = !hubSearchEnabled;
    setHubSaving(true);
    setHubError(null);
    try {
      const result = await prefsApi.setHubSearch(next);
      setHubSearchEnabled(result.hub_search_enabled);
    } catch (error) {
      setHubError(getErrorMessage(error, "Couldn’t update Hub search access."));
    } finally {
      setHubSaving(false);
    }
  };

  return (
    <section className="settings-view" aria-labelledby="settings-title" style={{ flex: 1, overflowY: "auto", padding: "32px 24px" }}>
      <div className="settings-inner" style={{ maxWidth: 560 }}>
        <h1 id="settings-title" className="settings-title" style={{ color: "var(--text-primary)", margin: "0 0 32px" }}>
          Settings
        </h1>

        {loadError && (
          <StatusNotice
            tone="offline"
            title="Some settings are unavailable"
            message={loadError}
            actionLabel="Retry"
            onAction={() => void loadSettings()}
          />
        )}

        {loading && !loadError && (
          <div className="settings-loading" role="status"><Loader2 size={14} className="animate-spin" /> Loading settings…</div>
        )}

        {/* API Keys */}
        <div style={{ marginBottom: 40 }}>
          <h2 style={{
            fontSize: 14,
            fontWeight: 600,
            color: "var(--text-secondary)",
            margin: "0 0 8px",
          }}>
            API keys
          </h2>

          {API_KEYS.map((apiKey) => (
            <div
              key={apiKey.key}
              style={{
                padding: "16px 0",
                borderTop: "1px solid var(--border-subtle)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 14, fontWeight: 500, color: "var(--text-primary)" }}>
                  {apiKey.label}
                </span>
                {saved[apiKey.envVar] && (
                  <span role="status" style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "var(--success)" }}>
                    <Check size={12} /> Saved
                  </span>
                )}
                {dirty[apiKey.envVar] && !saving[apiKey.envVar] && !errors[apiKey.envVar] && (
                  <span role="status" className="unsaved-indicator">Unsaved changes</span>
                )}
                {saving[apiKey.envVar] && (
                  <span role="status" className="saving-indicator"><Loader2 size={12} className="animate-spin" /> Saving…</span>
                )}
                {errors[apiKey.envVar] && (
                  <span id={`${apiKey.key}-error`} role="alert" style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "var(--error)" }}>
                    <AlertCircle size={12} /> {errors[apiKey.envVar]}
                  </span>
                )}
              </div>
              <p id={`${apiKey.key}-description`} style={{ fontSize: 12, color: "var(--text-tertiary)", margin: "0 0 10px" }}>
                {apiKey.description}
              </p>
              <div style={{ display: "flex", gap: 8 }}>
                <div style={{ flex: 1, position: "relative" }}>
                  <input
                    id={`${apiKey.key}-key`}
                    type={visibility[apiKey.key] ? "text" : "password"}
                    value={keys[apiKey.envVar] || ""}
                    onChange={(e) => handleChange(apiKey.envVar, e.target.value)}
                    placeholder={apiKey.placeholder}
                    autoComplete="off"
                    aria-label={`${apiKey.label} API key`}
                    aria-invalid={Boolean(errors[apiKey.envVar])}
                    aria-describedby={`${apiKey.key}-description${errors[apiKey.envVar] ? ` ${apiKey.key}-error` : ""}`}
                    style={{
                      width: "100%",
                      padding: "7px 36px 7px 10px",
                      background: "var(--bg-primary)",
                      border: "1px solid var(--border-default)",
                      borderRadius: 6,
                      color: "var(--text-primary)",
                      fontSize: 14,
                      fontFamily: "var(--font-mono)",
                      outline: "none",
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && dirty[apiKey.envVar]) {
                        void handleSave(apiKey, keys[apiKey.envVar] || "");
                      }
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => handleToggleVisibility(apiKey)}
                    disabled={revealing[apiKey.envVar] || saving[apiKey.envVar]}
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
                  onClick={() => void handleSave(apiKey, keys[apiKey.envVar] || "")}
                  disabled={!dirty[apiKey.envVar] || revealing[apiKey.envVar] || saving[apiKey.envVar]}
                  style={{
                    padding: "7px 14px",
                    background: "var(--bg-surface)",
                    border: "1px solid var(--border-default)",
                    borderRadius: 6,
                    color: "var(--text-secondary)",
                    fontSize: 14,
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

        {reloadNeeded && (
          <div className="reload-models-callout" role="status">
            <div>
              <strong>Hugging Face token updated</strong>
              <span>Reload the model library to apply the new access.</span>
            </div>
            {onReloadModels && (
              <button type="button" onClick={() => { setReloadNeeded(false); onReloadModels(); }}>
                <RefreshCw size={13} aria-hidden="true" /> Reload models
              </button>
            )}
          </div>
        )}

        <div className="settings-section">
          <div className="settings-section-heading">
            <div>
              <h2>External access</h2>
              <p>Control whether model searches can be sent to Hugging Face.</p>
            </div>
            <button
              type="button"
              className="switch-control"
              role="switch"
              aria-checked={hubSearchEnabled}
              aria-label="Allow Hugging Face Hub search"
              disabled={hubSaving}
              onClick={() => void handleHubSearchToggle()}
            >
              <span aria-hidden="true" />
              {hubSaving ? "Saving…" : hubSearchEnabled ? "Allowed" : "Off"}
            </button>
          </div>
          {hubError && <div className="settings-inline-error" role="alert">{hubError}</div>}
          <p className="settings-note">
            When enabled, search terms are sent to huggingface.co. Turn this off at any time to revoke access.
          </p>
        </div>

        {/* Info */}
        <div style={{
          fontSize: 12,
          color: "var(--text-muted)",
          borderTop: "1px solid var(--border-subtle)",
          paddingTop: 16,
        }}>
          Keys are saved to <code style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            padding: "1px 4px",
            background: "var(--bg-elevated)",
            borderRadius: 3,
          }}>.env</code> and applied locally.
        </div>
      </div>
    </section>
  );
}
