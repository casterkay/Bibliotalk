import { NextResponse } from "next/server";

import { setAdminCookie } from "@/lib/server/console_auth";

type LoginRequest = { token?: string };

function expectedToken(): string {
  const token = (process.env.BIBLIOTALK_ADMIN_TOKEN || "").trim();
  if (!token) throw new Error("Missing BIBLIOTALK_ADMIN_TOKEN");
  return token;
}

export async function POST(request: Request): Promise<NextResponse> {
  const body = (await request.json().catch(() => ({}))) as LoginRequest;
  const supplied = (body.token || "").trim();
  const expected = expectedToken();

  if (!supplied || supplied !== expected) {
    return NextResponse.json({ detail: "Invalid token" }, { status: 401 });
  }

  const response = NextResponse.json({ ok: true }, { status: 200 });
  setAdminCookie(response, supplied);
  return response;
}
