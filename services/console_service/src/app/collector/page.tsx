"use client";

import { useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { TopNav } from "@/components/TopNav";
import { apiGet, apiPost } from "@/lib/api";

type Agent = { agent_id: string; display_name: string; slug: string };

export default function CollectorPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState<string>("");
  const [result, setResult] = useState<any>(null);
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
          <h1 className="text-xl font-semibold">Collector: Run Once</h1>
          <div className="text-sm text-gray-600">Trigger one poll/ingest cycle and inspect status.</div>
        </div>
        {err ? <div className="mb-3 text-sm text-red-600">{err}</div> : null}

        <div className="mb-3 flex items-center gap-2">
          <select
            className="rounded border bg-white px-3 py-2 text-sm"
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
          >
            <option value="">All agents</option>
            {agents.map((a) => (
              <option key={a.agent_id} value={a.agent_id}>
                {a.display_name} ({a.slug})
              </option>
            ))}
          </select>
          <button
            className="rounded bg-black px-3 py-2 text-sm text-white hover:bg-gray-800"
            onClick={async () => {
              setErr(null);
              setResult(null);
              try {
                const res = await apiPost("/api/collector/run-once", {
                  agent_id: agentId || null,
                });
                setResult(res);
              } catch (e: any) {
                setErr(e?.detail || "Run failed");
              }
            }}
          >
            Run once
          </button>
        </div>

        <div className="rounded-lg border bg-white p-4">
          <div className="mb-2 text-sm font-semibold">Result</div>
          <pre className="max-h-[70vh] overflow-auto rounded bg-gray-50 p-3 text-xs">
            {result ? JSON.stringify(result, null, 2) : "—"}
          </pre>
        </div>
      </div>
    </RequireAuth>
  );
}
