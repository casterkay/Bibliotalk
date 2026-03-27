"use client";

import { useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { TopNav } from "@/components/TopNav";
import { apiGet, apiPost } from "@/lib/api";

type Agent = { agent_id: string; display_name: string; slug: string };

export default function EMOSPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState<string>("");
  const [groupId, setGroupId] = useState<string>("");
  const [payload, setPayload] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    apiGet<any[]>("/api/agents")
      .then((rows) => setAgents(rows))
      .catch((e: any) => setErr(e?.detail || "Failed to load agents"));
  }, []);

  return (
    <RequireAuth>
      <TopNav />
      <div className="mx-auto max-w-6xl px-4 py-6">
        <div className="mb-4">
          <h1 className="text-xl font-semibold">EverMemOS Browser</h1>
          <div className="text-sm text-gray-600">Raw `/memories/get` for an agent.</div>
        </div>
        {err ? <div className="mb-3 text-sm text-red-600">{err}</div> : null}

        <div className="mb-3 grid gap-2 md:grid-cols-3">
          <select
            className="rounded border bg-white px-3 py-2 text-sm"
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
          >
            <option value="">Select agent</option>
            {agents.map((a) => (
              <option key={a.agent_id} value={a.agent_id}>
                {a.display_name} ({a.slug})
              </option>
            ))}
          </select>
          <input
            className="rounded border bg-white px-3 py-2 text-sm font-mono"
            placeholder="group_id (optional)"
            value={groupId}
            onChange={(e) => setGroupId(e.target.value)}
          />
          <button
            className="rounded bg-black px-3 py-2 text-sm text-white hover:bg-gray-800 disabled:opacity-50"
            disabled={!agentId}
            onClick={async () => {
              setErr(null);
              setPayload(null);
              try {
                const res = await apiPost("/api/emos/memories/get", {
                  agent_id: agentId,
                  group_id: groupId || null,
                  memory_type: "episodic_memory",
                  limit: 50,
                  offset: 0,
                });
                setPayload(res);
              } catch (e: any) {
                setErr(e?.detail || "Request failed");
              }
            }}
          >
            Get
          </button>
        </div>

        <div className="rounded-lg border bg-white p-4">
          <pre className="max-h-[75vh] overflow-auto rounded bg-gray-50 p-3 text-xs">
            {payload ? JSON.stringify(payload, null, 2) : "—"}
          </pre>
        </div>
      </div>
    </RequireAuth>
  );
}
