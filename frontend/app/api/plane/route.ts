import { allowed, callPlane } from "../../lib/ops";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const input = await request.json().catch(() => null);
  const target = String(input?.target ?? "");
  const method = String(input?.method ?? "");
  const route = String(input?.path ?? "");
  if (!allowed(target, method, route)) return Response.json({ error: "operation not allowed" }, { status: 400 });
  const body = input?.body;
  if (body !== undefined && (typeof body !== "object" || body === null || JSON.stringify(body).length > 8192)) {
    return Response.json({ error: "invalid body" }, { status: 400 });
  }
  return Response.json(await callPlane(target, method, route, body));
}
