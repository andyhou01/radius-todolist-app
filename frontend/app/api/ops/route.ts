import { make } from "../../lib/ops";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const kind = new URL(request.url).searchParams.get("kind") === "report" ? "report" : "endpoints";
  return Response.json(await make(kind));
}
