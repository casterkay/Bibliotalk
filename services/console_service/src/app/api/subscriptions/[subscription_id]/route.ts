import { NextResponse, type NextRequest } from "next/server";

import { requireAuthenticated } from "@/lib/server/console_auth";
import { proxyJson } from "@/lib/server/memories_client";

type Params = { subscription_id: string };

export async function PATCH(
  request: NextRequest,
  context: { params: Params },
): Promise<NextResponse> {
  const auth = requireAuthenticated(request);
  if (auth) return auth;
  const body = await request.json();
  return proxyJson(`/v1/admin/subscriptions/${context.params.subscription_id}`, {
    method: "PATCH",
    bodyJson: body,
  });
}
