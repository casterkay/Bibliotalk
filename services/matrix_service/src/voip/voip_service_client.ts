export async function ensureVoipBridge(params: {
  voipServiceUrl: string;
  roomId: string;
  spiritUserId: string;
  agentId: string;
  livekitServiceUrl: string;
}): Promise<void> {
  const base = params.voipServiceUrl.replace(/\/$/, "");
  const res = await fetch(`${base}/v1/voip/ensure`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      room_id: params.roomId,
      spirit_user_id: params.spiritUserId,
      agent_id: params.agentId,
      livekit_service_url: params.livekitServiceUrl,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`voip_service ensure failed (${res.status}): ${text}`);
  }
}
