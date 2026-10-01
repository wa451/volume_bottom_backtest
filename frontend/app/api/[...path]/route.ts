import { NextRequest } from "next/server";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
async function forward(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  if (
    !["defaults", "market-data", "jobs", "backtests"].includes(path[0]) ||
    path.some((p) => p === ".." || /[\\/]/.test(p))
  )
    return Response.json({ detail: "Unknown API path" }, { status: 404 });
  const origin = (process.env.BACKEND_URL || "http://127.0.0.1:8000").replace(
    /\/$/,
    "",
  );
  const url =
    origin +
    "/api/" +
    path.map(encodeURIComponent).join("/") +
    request.nextUrl.search;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (process.env.API_TOKEN)
    headers.Authorization = "Bearer " + process.env.API_TOKEN;
  const key = request.headers.get("Idempotency-Key");
  if (key) headers["Idempotency-Key"] = key;
  try {
    const response = await fetch(url, {
      method: request.method,
      headers,
      body: request.method === "POST" ? await request.text() : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(120_000),
    });
    const out = new Headers();
    for (const h of ["content-type", "content-disposition"]) {
      const v = response.headers.get(h);
      if (v) out.set(h, v);
    }
    out.set("Cache-Control", "no-store");
    return new Response(response.body, {
      status: response.status,
      headers: out,
    });
  } catch {
    return Response.json(
      {
        detail:
          "Backend APIに接続できません。APIとWorkerの起動を確認してください。",
      },
      { status: 503 },
    );
  }
}
export const GET = forward;
export const POST = forward;
