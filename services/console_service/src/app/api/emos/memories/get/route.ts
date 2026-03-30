import { NextResponse, type NextRequest } from "next/server";

import { requireAuthenticated } from "@/lib/server/console_auth";
import { proxyJson } from "@/lib/server/memories_client";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const auth = requireAuthenticated(request);
  if (auth) return auth;
  const body = await request.json();
  return proxyJson("/v1/admin/emos/memories/get", { method: "POST", bodyJson: body });
}
