import { RECONCILERS_URL } from "../../lib/demo";

export async function GET() {
  try {
    const upstream = await fetch(`${RECONCILERS_URL}/`, { cache: "no-store", signal: AbortSignal.timeout(5000) });
    return Response.json(await upstream.json());
  } catch {
    return Response.json({ error: "reconcilers unreachable" }, { status: 502 });
  }
}
