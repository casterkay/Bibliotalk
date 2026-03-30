import { NextResponse, type NextRequest } from "next/server";

import { requireAuthenticated } from "@/lib/server/console_auth";
import { forwardResponse } from "@/lib/server/forward_response";
import { memoriesFetch } from "@/lib/server/memories_client";

type AgentSummary = { slug: string };
type IngestBatchRequest = { agent_id?: string; urls?: string[]; max_items?: number | null };

export async function POST(request: NextRequest): Promise<NextResponse> {
  const auth = requireAuthenticated(request);
  if (auth) return auth;

  const body = (await request.json().catch(() => ({}))) as IngestBatchRequest;
  const agentId = (body.agent_id || "").trim();
  if (!agentId) return NextResponse.json({ detail: "Missing agent_id" }, { status: 400 });

  const urls = (body.urls || []).map((u) => String(u).trim()).filter(Boolean);
  if (urls.length === 0) return NextResponse.json({ detail: "Provide urls[]" }, { status: 400 });

  const agentResp = await memoriesFetch(`/v1/admin/agents/${agentId}`, { method: "GET" });
  if (!agentResp.ok) return forwardResponse(agentResp);
  const agent = (await agentResp.json()) as AgentSummary;
  const agentSlug = (agent.slug || "").trim();
  if (!agentSlug) return NextResponse.json({ detail: "Invalid agent slug" }, { status: 500 });

  const resp = await memoriesFetch("/v1/ingest-batch", {
    method: "POST",
    bodyJson: {
      agent_slug: agentSlug,
      urls,
      max_items: body.max_items ?? null,
    },
  });
  return forwardResponse(resp);
}
