// Server-only: runs the project's operator scripts. Never import from client components.
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";

const run = promisify(execFile);

export type OpResult = { ok: boolean; status: number | null; stdout: string; stderr: string; json: unknown };

export function repoRoot(): string {
  const cwd = process.cwd();
  for (const candidate of [cwd, path.resolve(cwd, "..")]) {
    if (existsSync(path.join(candidate, "scripts", "operations", "api.sh"))) return candidate;
  }
  return cwd;
}

const TARGET = /^(management|(control|data):(shared|isolated-[1-9][0-9]?))$/;
const ID = "[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?";
const ROUTES: [string, RegExp][] = [
  ["GET", /^\/healthz$/],
  ["POST", /^\/tenants$/],
  ["GET", new RegExp(`^/tenants/${ID}(\\?limit=\\d{1,3})?$`)],
  ["GET", new RegExp(`^/tenants/${ID}/llm/usage$`)],
  ["PUT", new RegExp(`^/tenants/${ID}/configuration$`)],
  ["POST", new RegExp(`^/tenants/${ID}/(counter|chat/completions)$`)],
  ["GET", /^\/operations\/[0-9a-f-]{36}$/],
];

export function allowed(target: string, method: string, route: string): boolean {
  return TARGET.test(target) && ROUTES.some(([m, re]) => m === method && re.test(route));
}

function parse(text: string): unknown {
  try {
    return JSON.parse(text.trim());
  } catch {
    return null;
  }
}

async function exec(file: string, args: string[]): Promise<OpResult> {
  const options = { cwd: repoRoot(), timeout: 45000, maxBuffer: 2 * 1024 * 1024, env: { ...process.env, COLOR: "never" } };
  let stdout = "";
  let stderr = "";
  let ok = true;
  try {
    ({ stdout, stderr } = await run(file, args, options));
  } catch (error) {
    const failed = error as { stdout?: string; stderr?: string };
    ok = false;
    stdout = failed.stdout ?? "";
    stderr = failed.stderr ?? String(error);
  }
  const status = Number(stderr.match(/HTTP (\d{3})/)?.[1]) || null;
  return { ok, status, stdout, stderr, json: parse(stdout) };
}

// Calls a plane through the project's own api.sh, which discovers the endpoint and key.
export function callPlane(target: string, method: string, route: string, body?: unknown): Promise<OpResult> {
  const args = [path.join(repoRoot(), "scripts", "operations", "api.sh"), target, method, route];
  if (body !== undefined) args.push(JSON.stringify(body));
  return exec("bash", args);
}

export function make(target: "endpoints" | "report"): Promise<OpResult> {
  return exec("make", target === "endpoints" ? ["endpoints", "ARGS=all"] : ["report"]);
}
