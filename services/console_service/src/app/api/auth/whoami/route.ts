import { NextResponse, type NextRequest } from "next/server";

import { isAuthenticated } from "@/lib/server/console_auth";

export async function GET(request: NextRequest): Promise<NextResponse> {
  return NextResponse.json(
    { ok: true, authenticated: isAuthenticated(request) },
    { status: 200 },
  );
}
