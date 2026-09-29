import { GATEWAY_URL, MODELS, TENANT_KEYS } from "../../lib/demo";

type Stage = { name: string; phase: string; result: "pass" | "block" | "skip"; detail: string };

// Explain which phase handled the request, based only on the gateway's observable response.
function explain(status: number, body: string, model: string): Stage[] {
  let parsed: { error?: string; reason?: string; rule?: string; choices?: { message?: { content?: string } }[] } = {};
  try {
    parsed = JSON.parse(body);
  } catch {}
  const content = parsed.choices?.[0]?.message?.content ?? "";
  const target = content.startsWith("[vendor-hosted") ? "Vendor-hosted models" : "Azure-hosted models";
  const stages: Stage[] = [
    { name: "Gateway: validate API key", phase: "PreRouting", result: "pass", detail: "API key accepted" },
    { name: "Passport Control", phase: "PreRouting", result: "pass", detail: "Signed passport issued" },
    { name: "Guardrails", phase: "PreRouting", result: "pass", detail: "No rule matched" },
    { name: "Policy", phase: "PreRouting", result: "pass", detail: "Tenant may use this model" },
    { name: "Router", phase: "Route selection", result: "pass", detail: `Model ${model} -> ${target}` },
    { name: "Audit event tap", phase: "PostRouting", result: "pass", detail: "Passport verified, event published" },
    { name: "AI Gateway -> model", phase: "Backend", result: "pass", detail: content.includes("<EMAIL_ADDRESS>") ? "Response email masked" : "Response returned" },
  ];
  let blockedAt = -1;
  if (status === 401) {
    blockedAt = 0;
    stages[0].detail = body.trim() || "Missing or invalid API key";
  } else if (parsed.error === "guardrail_rejected") {
    blockedAt = 2;
    stages[2].detail = `Rejected by rule ${parsed.rule}`;
  } else if (parsed.error === "policy_denied") {
    blockedAt = 3;
    stages[3].detail = parsed.reason ?? "Denied";
  } else if (status === 429) {
    blockedAt = 5;
    stages[5].detail = "Rate limit exceeded";
  } else if (status !== 200) {
    blockedAt = 1;
    stages[1].detail = `Unexpected status ${status}`;
  }
  if (blockedAt >= 0) {
    stages[blockedAt].result = "block";
    for (const stage of stages.slice(blockedAt + 1)) {
      stage.result = "skip";
      stage.detail = "Not reached";
    }
  }
  return stages;
}

export async function POST(request: Request) {
  const input = await request.json().catch(() => null);
  const tenant = String(input?.tenant ?? "");
  const model = String(input?.model ?? "");
  const prompt = String(input?.prompt ?? "");
  if (!(tenant in TENANT_KEYS) || !(MODELS as readonly string[]).includes(model) || !prompt || prompt.length > 2000) {
    return Response.json({ error: "invalid input" }, { status: 400 });
  }
  const key = TENANT_KEYS[tenant];
  const started = Date.now();
  try {
    const upstream = await fetch(`${GATEWAY_URL}/v1/chat/completions`, {
      method: "POST",
      headers: { "content-type": "application/json", ...(key ? { "x-api-key": key } : {}) },
      body: JSON.stringify({ model, messages: [{ role: "user", content: prompt }] }),
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    const body = await upstream.text();
    return Response.json({
      status: upstream.status,
      durationMs: Date.now() - started,
      body,
      stages: explain(upstream.status, body, model),
    });
  } catch {
    return Response.json({ error: "gateway unreachable" }, { status: 502 });
  }
}
