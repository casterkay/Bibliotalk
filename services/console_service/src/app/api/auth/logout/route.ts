import { NextResponse } from "next/server";

import { clearAdminCookie } from "@/lib/server/console_auth";

export async function POST(): Promise<NextResponse> {
  const response = NextResponse.json({ ok: true }, { status: 200 });
  clearAdminCookie(response);
  return response;
}
