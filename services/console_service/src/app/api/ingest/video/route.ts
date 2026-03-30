import { NextResponse, type NextRequest } from "next/server";

import { requireAuthenticated } from "@/lib/server/console_auth";
import { forwardResponse } from "@/lib/server/forward_response";
import { memoriesFetch } from "@/lib/server/memories_client";

type AgentSummary = { slug: string };
type IngestVideoRequest = { agent_id?: string; url?: string; title?: string | null };

export async function POST(request: NextRequest): Promise<NextResponse> {
  const auth = requireAuthenticated(request);
  if (auth) return auth;

  const body = (await request.json().catch(() => ({}))) as IngestVideoRequest;
  const agentId = (body.agent_id || "").trim();
  if (!agentId) return NextResponse.json({ detail: "Missing agent_id" }, { status: 400 });

  const agentResp = await memoriesFetch(`/v1/admin/agents/${agentId}`, { method: "GET" });
  if (!agentResp.ok) return forwardResponse(agentResp);
  const agent = (await agentResp.json()) as AgentSummary;
  const agentSlug = (agent.slug || "").trim();
  if (!agentSlug) return NextResponse.json({ detail: "Invalid agent slug" }, { status: 500 });

  const resp = await memoriesFetch("/v1/ingest", {
    method: "POST",
    bodyJson: {
      agent_slug: agentSlug,
      url: body.url,
      title: body.title ?? null,
    },
  });
  return forwardResponse(resp);
}
