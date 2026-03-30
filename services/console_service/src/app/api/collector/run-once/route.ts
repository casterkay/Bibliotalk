import { NextResponse, type NextRequest } from "next/server";

import { requireAuthenticated } from "@/lib/server/console_auth";
import { forwardResponse } from "@/lib/server/forward_response";
import { memoriesFetch } from "@/lib/server/memories_client";

type AgentSummary = { slug: string };
type CollectorRequest = { agent_id?: string | null };

export async function POST(request: NextRequest): Promise<NextResponse> {
  const auth = requireAuthenticated(request);
  if (auth) return auth;

  const body = (await request.json().catch(() => ({}))) as CollectorRequest;
  const agentId = typeof body.agent_id === "string" ? body.agent_id.trim() : null;

  let agentSlug: string | null = null;
  if (agentId) {
    const agentResp = await memoriesFetch(`/v1/admin/agents/${agentId}`, { method: "GET" });
    if (!agentResp.ok) return forwardResponse(agentResp);
    const agent = (await agentResp.json()) as AgentSummary;
    agentSlug = (agent.slug || "").trim() || null;
  }

  const resp = await memoriesFetch("/v1/admin/collector/run-once", {
    method: "POST",
    bodyJson: { agent_slug: agentSlug },
  });
  return forwardResponse(resp);
}
