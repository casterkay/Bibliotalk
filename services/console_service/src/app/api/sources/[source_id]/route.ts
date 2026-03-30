import { NextResponse, type NextRequest } from "next/server";

import { requireAuthenticated } from "@/lib/server/console_auth";
import { proxyJson } from "@/lib/server/memories_client";

type Params = { source_id: string };

export async function DELETE(
  request: NextRequest,
  context: { params: Params },
): Promise<NextResponse> {
  const auth = requireAuthenticated(request);
  if (auth) return auth;
  return proxyJson(`/v1/admin/sources/${context.params.source_id}`, { method: "DELETE" });
}
