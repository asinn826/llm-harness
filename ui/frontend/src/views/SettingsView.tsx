import { useState, useEffect } from "react";
import { Eye, EyeOff, Check, AlertCircle } from "lucide-react";

interface ApiKey {
  key: string;
  envVar: string;
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
  const [visibility, setVisibility] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Load current keys on mount
  useEffect(() => {
    fetch("/api/settings/keys")
      .then((r) => r.json())
      .then((data) => setKeys(data))
      .catch(() => {});
  }, []);

  const handleSave = async (envVar: string, value: string) => {
    try {
      const res = await fetch("/api/settings/keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: envVar, value }),
      });
      if (!res.ok) throw new Error("Failed to save");
      setSaved((s) => ({ ...s, [envVar]: true }));
      setErrors((e) => ({ ...e, [envVar]: "" }));
      setTimeout(() => setSaved((s) => ({ ...s, [envVar]: false })), 2000);
    } catch (err) {
      setErrors((e) => ({ ...e, [envVar]: "Failed to save" }));
    }
  };

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "32px 24px" }}>
      <div style={{ maxWidth: 560 }}>
        <h1 style={{ fontSize: 18, fontWeight: 600, color: "var(--text-primary)", margin: "0 0 4px" }}>
          Settings
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-tertiary)", margin: "0 0 32px" }}>
          API keys are stored in your local .env file and never sent anywhere.
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
                    onChange={(e) => setKeys((k) => ({ ...k, [apiKey.envVar]: e.target.value }))}
                    placeholder={apiKey.placeholder}
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
                      if (e.key === "Enter") handleSave(apiKey.envVar, keys[apiKey.envVar] || "");
                    }}
                  />
                  <button
                    onClick={() => setVisibility((v) => ({ ...v, [apiKey.key]: !v[apiKey.key] }))}
                    style={{
                      position: "absolute",
                      right: 8,
                      top: "50%",
                      transform: "translateY(-50%)",
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      color: "var(--text-muted)",
                      padding: 2,
                    }}
                  >
                    {visibility[apiKey.key] ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
                <button
                  onClick={() => handleSave(apiKey.envVar, keys[apiKey.envVar] || "")}
                  style={{
                    padding: "7px 14px",
                    background: "var(--bg-surface)",
                    border: "1px solid var(--border-default)",
                    borderRadius: 6,
                    color: "var(--text-secondary)",
                    fontSize: 12,
                    fontWeight: 500,
                    cursor: "pointer",
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
