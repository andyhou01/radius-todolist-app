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

export type PersonaKey = "platform" | "tenant-admin" | "end-user";

export const PERSONAS: Record<PersonaKey, { who: string; plane: string; goal: string; home: string; nav: { href: string; label: string }[] }> = {
  platform: {
    who: "Platform admin",
    plane: "Management plane",
    goal: "Onboards tenants, allocates cluster pairs and runs the environment.",
    home: "/",
    nav: [
      { href: "/", label: "Planes" },
      { href: "/tenants", label: "Tenants" },
      { href: "/operations", label: "Operations" },
    ],
  },
  "tenant-admin": {
    who: "Tenant admin",
    plane: "Control plane",
    goal: "Owns the desired configuration of one tenant and watches it roll out.",
    home: "/configuration",
    nav: [
      { href: "/configuration", label: "Configuration" },
      { href: "/gateway", label: "Gateway policies" },
    ],
  },
  "end-user": {
    who: "End user",
    plane: "Data plane",
    goal: "Uses the running tenant application. Keeps working if Control is down.",
    home: "/workspace",
    nav: [
      { href: "/workspace", label: "Application" },
      { href: "/playground", label: "AI Playground" },
    ],
  },
};

export const PERSONA_KEYS = Object.keys(PERSONAS) as PersonaKey[];

export function personaForPath(pathname: string): PersonaKey | null {
  for (const key of PERSONA_KEYS) {
    if (PERSONAS[key].nav.some((n) => (n.href === "/" ? pathname === "/" : pathname.startsWith(n.href)))) return key;
  }
  return null;
}

export const PLANES: { target: string; name: string; role: string; pair: string }[] = [
  { target: "management", name: "Management", role: "Accepts tenants, allocates cluster pairs, provisions via Radius", pair: "-" },
  { target: "control:shared", name: "Control", role: "Desired tenant configuration", pair: "shared" },
  { target: "data:shared", name: "Data", role: "Tenant runtime API, Redis, agentgateway", pair: "shared" },
  { target: "control:isolated-1", name: "Control", role: "Desired tenant configuration", pair: "isolated-1" },
  { target: "data:isolated-1", name: "Data", role: "Tenant runtime API, Redis, agentgateway", pair: "isolated-1" },
];

export const pairTargets = (pairId: string) => ({ control: `control:${pairId}`, data: `data:${pairId}` });

// Resolves which cluster pair serves a tenant. Management is the only directory of pairs.
export async function resolvePair(tenant: string): Promise<{ pair: string | null; error: string }> {
  const result = await plane("management", "GET", `/tenants/${tenant}`);
  const pair = (result.json as { pair_id?: string } | null)?.pair_id ?? null;
  return { pair: result.ok ? pair : null, error: result.ok ? (pair ? "" : "Tenant has no cluster pair yet") : errorText(result) };
}

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
