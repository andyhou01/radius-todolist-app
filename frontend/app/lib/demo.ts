// Server-only demo settings. API keys never reach the browser.
export const GATEWAY_URL = process.env.GATEWAY_URL ?? "http://127.0.0.1:35521";
export const RECONCILERS_URL = process.env.RECONCILERS_URL ?? "http://127.0.0.1:35522";

// Synthetic demo keys from demos/agentgateway-filters/config.yaml.
export const TENANT_KEYS: Record<string, string | null> = {
  acme: "demo-key-acme",
  globex: "demo-key-globex",
  anonymous: null,
};

export const MODELS = ["gpt-4o-mini", "vendor-large"] as const;
