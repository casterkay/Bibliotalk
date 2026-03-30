import { NextResponse } from "next/server";

function memoriesServiceUrl(): string {
  const url = (process.env.MEMORIES_SERVICE_URL || "").trim();
  return url || "http://localhost:8080";
}

function adminToken(): string {
  const token = (process.env.BIBLIOTALK_ADMIN_TOKEN || "").trim();
  if (!token) throw new Error("Missing BIBLIOTALK_ADMIN_TOKEN");
  return token;
}

export async function memoriesFetch(
  path: string,
  init: RequestInit & { bodyJson?: unknown } = {},
): Promise<Response> {
  const base = memoriesServiceUrl().replace(/\/$/, "");
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;

  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${adminToken()}`);
  if (init.bodyJson !== undefined) {
    headers.set("content-type", "application/json");
  }

  return fetch(url, {
    ...init,
    headers,
    body: init.bodyJson === undefined ? init.body : JSON.stringify(init.bodyJson),
    cache: "no-store",
  });
}

export async function proxyJson(
  path: string,
  init: RequestInit & { bodyJson?: unknown } = {},
): Promise<NextResponse> {
  const resp = await memoriesFetch(path, init);

  const contentType = resp.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const json = await resp.json();
    return NextResponse.json(json, { status: resp.status });
  }

  const text = await resp.text();
  return new NextResponse(text, { status: resp.status });
}
