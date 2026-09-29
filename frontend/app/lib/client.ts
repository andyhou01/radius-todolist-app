"use client";

export type OpResult = { ok: boolean; status: number | null; stdout: string; stderr: string; json: unknown };

export async function plane(target: string, method: string, path: string, body?: unknown): Promise<OpResult> {
  const response = await fetch("/api/plane", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ target, method, path, body }),
  });
  const data = await response.json();
  if (!response.ok) return { ok: false, status: response.status, stdout: "", stderr: data.error ?? "failed", json: null };
  return data;
}

export const PLANES = [
  { target: "management", name: "Management", role: "Accepts tenants, allocates cluster pairs, provisions via Radius" },
  { target: "control:shared", name: "Control (shared)", role: "Desired tenant configuration for the shared pair" },
  { target: "data:shared", name: "Data (shared)", role: "Tenant runtime API, Redis, agentgateway" },
  { target: "control:isolated-1", name: "Control (isolated-1)", role: "Desired configuration for the isolated pair" },
  { target: "data:isolated-1", name: "Data (isolated-1)", role: "Isolated tenant runtime and agentgateway" },
];

export const pairTargets = (pairId: string) => ({ control: `control:${pairId}`, data: `data:${pairId}` });

const KEY = "demo.tenants";
export function knownTenants(): string[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}
export function rememberTenant(id: string) {
  localStorage.setItem(KEY, JSON.stringify([id, ...knownTenants().filter((t) => t !== id)].slice(0, 50)));
}
export function forgetTenant(id: string) {
  localStorage.setItem(KEY, JSON.stringify(knownTenants().filter((t) => t !== id)));
}

export function errorText(result: OpResult): string {
  const body = result.json as { error?: string; detail?: unknown } | null;
  const code = body?.error ?? (typeof body?.detail === "string" ? body.detail : "");
  return [result.status ? `HTTP ${result.status}` : "", code || result.stderr.split("\n").filter(Boolean).slice(-2).join(" ")]
    .filter(Boolean)
    .join(" · ");
}
