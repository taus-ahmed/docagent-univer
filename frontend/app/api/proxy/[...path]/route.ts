import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL || "http://localhost:8000";

// Next 15: dynamic route params arrive as a Promise.
async function handler(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const path = (await params).path.join("/");
  const url = `${BACKEND}/api/${path}${req.nextUrl.search}`;

  const headers: Record<string, string> = {};
  const ct = req.headers.get("content-type");
  if (ct) headers["content-type"] = ct;
  const auth = req.headers.get("authorization");
  if (auth) headers["authorization"] = auth;

  const isMultipart = (ct || "").includes("multipart");
  let body: BodyInit | null = null;
  if (req.method !== "GET" && req.method !== "HEAD") {
    body = isMultipart ? await req.blob() : await req.text();
    if (isMultipart) delete headers["content-type"];
  }

  try {
    const res = await fetch(url, { method: req.method, headers, body });
    const resBody = await res.blob();
    // The backend's caching policy travels with its answer: every /api/
    // response is one firm's data ("no-store"; page images "private"), and an
    // edge cache must not keep it for the next caller. Downloads keep their
    // file name.
    const out: Record<string, string> = {
      "content-type": res.headers.get("content-type") || "application/json",
      "cache-control": res.headers.get("cache-control") || "no-store",
    };
    for (const h of ["vary", "content-disposition"]) {
      const v = res.headers.get(h);
      if (v) out[h] = v;
    }
    return new NextResponse(resBody, { status: res.status, headers: out });
  } catch (e: any) {
    return NextResponse.json({ detail: `Proxy error: ${e.message}` }, { status: 502 });
  }
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const DELETE = handler;
export const OPTIONS = handler;
export const PATCH = handler;