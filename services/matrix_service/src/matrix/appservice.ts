import { randomUUID } from "node:crypto";

import type { FastifyPluginAsync } from "fastify";
import WebSocket from "ws";

import { renderCitedMessage, type CitationV1 } from "../render/matrix_message.js";
import { startStreamingMessage } from "../render/streaming_edits.js";
import { AppserviceAuthError, requireHsToken } from "./auth.js";
import { MatrixClient } from "./client.js";
import { parseTransaction, type MatrixCallMemberEvent, type MatrixRoomMessageEvent } from "./events.js";
import { shouldIgnoreMessage } from "./guards.js";
import { handleMembershipEvent, MembershipIndex } from "./membership.js";
import { routeMessageToSpirits } from "./routing.js";
import { extractLivekitServiceUrl } from "../voip/call_member.js";
import { ensureVoipBridge } from "../voip/voip_service_client.js";

type AgentTurnResult = {
  text: string;
  citations: CitationV1[];
  no_evidence?: boolean;
};

function env(name: string, fallback = ""): string {
  return process.env[name] ?? fallback;
}

function parseAgentIdFromSpiritUserId(userId: string, spiritUserPrefix: string): string | null {
  // Expected format: @<prefix><uuid>:server (prefix includes trailing underscore, e.g. "bt_")
  if (!userId.startsWith(`@${spiritUserPrefix}`)) return null;
  const localpart = userId.slice(1).split(":", 1)[0];
  const raw = localpart.slice(spiritUserPrefix.length);
  const uuidRe =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  return uuidRe.test(raw) ? raw : null;
}

async function createLiveSession(params: {
  agentsBaseUrl: string;
  agentId: string;
  platform: string;
  roomId: string;
  initiatorPlatformUserId: string;
  modality: "text" | "voice";
}): Promise<{ session_id: string; ws_url: string }> {
  const url = `${params.agentsBaseUrl.replace(/\\/$/, "")}/v1/agents/${params.agentId}/live/sessions`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      platform: params.platform,
      room_id: params.roomId,
      initiator_platform_user_id: params.initiatorPlatformUserId,
      modality: params.modality,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`agents_service live session failed (${res.status}): ${text}`);
  }
  return (await res.json()) as { session_id: string; ws_url: string };
}

async function callTurnFallback(params: {
  agentsBaseUrl: string;
  agentId: string;
  platform: string;
  roomId: string;
  eventId: string | null;
  senderPlatformUserId: string;
  text: string;
  mentions: string[];
}): Promise<AgentTurnResult> {
  const url = `${params.agentsBaseUrl.replace(/\\/$/, "")}/v1/agents/${params.agentId}/turn`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      platform: params.platform,
      room_id: params.roomId,
      event_id: params.eventId,
      sender_platform_user_id: params.senderPlatformUserId,
      sender_display_name: null,
      text: params.text,
      mentions: params.mentions,
      timestamp: new Date().toISOString(),
      modality: "text",
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`agents_service turn failed (${res.status}): ${text}`);
  }
  return (await res.json()) as AgentTurnResult;
}

async function runLiveTurn(params: {
  agentsWsUrl: string;
  prompt: string;
  onDelta: (delta: string) => Promise<void>;
}): Promise<{ text: string; citations: CitationV1[] }> {
  const turnId = randomUUID();
  const ws = new WebSocket(params.agentsWsUrl);

  let finalText = "";
  let citations: CitationV1[] = [];

  await new Promise<void>((resolve, reject) => {
    ws.on("open", () => resolve());
    ws.on("error", (err) => reject(err));
  });

  ws.send(
    JSON.stringify({
      type: "input.text",
      ts: new Date().toISOString(),
      turn_id: turnId,
      payload: { text: params.prompt },
    }),
  );

  await new Promise<void>((resolve, reject) => {
    ws.on("message", async (data) => {
      try {
        const msg = JSON.parse(data.toString("utf-8")) as any;
        if (msg.turn_id !== turnId) return;
        const type = msg.type as string;
        const payload = msg.payload ?? {};

        if (type === "output.text.delta") {
          const delta = String(payload.text ?? "");
          if (delta) {
            await params.onDelta(delta);
            finalText += delta;
          }
          return;
        }
        if (type === "output.text.final") {
          const text = String(payload.text ?? "");
          finalText = text || finalText;
          return;
        }
        if (type === "output.citations.final") {
          citations = (payload.items ?? []) as CitationV1[];
          return;
        }
        if (type === "output.turn.end") {
          resolve();
          return;
        }
        if (type === "error") {
          reject(new Error(String(payload.message ?? "agent error")));
        }
      } catch (err) {
        reject(err);
      }
    });
    ws.on("error", (err) => reject(err));
    ws.on("close", () => resolve());
  });

  ws.close();
  return { text: finalText, citations };
}

export const createAppserviceRouter = (): FastifyPluginAsync => {
  const plugin: FastifyPluginAsync = async (app) => {
    const spiritUserPrefix = env("MATRIX_SPIRIT_USER_PREFIX", "bt_");
    const homeserverUrl = env("MATRIX_HOMESERVER_URL", "http://localhost:8008");
    const asToken = env("MATRIX_AS_TOKEN");
    const agentsBaseUrl = env("AGENTS_SERVICE_URL", "http://localhost:8009");
    const voipServiceUrl = env("VOIP_SERVICE_URL", "http://localhost:9012");
    const fallbackLivekitServiceUrl = env("VOIP_LIVEKIT_SERVICE_URL", "");

    if (!asToken) {
      app.log.warn("MATRIX_AS_TOKEN is not configured; matrix_service cannot send messages");
    }

    const client = new MatrixClient({ homeserverUrl, asToken });
    const membershipIndex = new MembershipIndex();

    app.addHook("preHandler", async (request, reply) => {
      try {
        requireHsToken(request);
      } catch (err) {
        if (err instanceof AppserviceAuthError) {
          await reply.code(401).send({ error: "unauthorized" });
          return reply;
        }
        throw err;
      }
      return undefined;
    });

    const handleTxn = async (body: unknown) => {
      const txn = parseTransaction(body);
      for (const event of txn.events) {
        if (event.type === "m.room.member") {
          await handleMembershipEvent(event, {
            client,
            index: membershipIndex,
            config: { spiritUserPrefix },
          });
          continue;
        }

        if (event.type === "org.matrix.msc3401.call.member") {
          await handleCallMemberEvent(event, {
            spiritUserPrefix,
            membershipIndex,
            voipServiceUrl,
            fallbackLivekitServiceUrl,
          });
          continue;
        }

        if (event.type !== "m.room.message") continue;
        if (shouldIgnoreMessage(event, { spiritUserPrefix })) continue;

        const spirits = routeMessageToSpirits(event, membershipIndex, { spiritUserPrefix });
        if (spirits.length === 0) continue;

        await Promise.all(
          spirits.map(async (spiritUserId) => {
            await handleSpiritMessage({
              event,
              spiritUserId,
              spiritUserPrefix,
              client,
              agentsBaseUrl,
            });
          }),
        );
      }
    };

    async function handleCallMemberEvent(
      event: MatrixCallMemberEvent,
      deps: {
        spiritUserPrefix: string;
        membershipIndex: MembershipIndex;
        voipServiceUrl: string;
        fallbackLivekitServiceUrl: string;
      },
    ): Promise<void> {
      const spirits = deps.membershipIndex.getRoomSpirits(event.room_id);
      if (spirits.length !== 1) return;

      const spiritUserId = spirits[0];
      const agentId = parseAgentIdFromSpiritUserId(spiritUserId, deps.spiritUserPrefix);
      if (!agentId) return;

      const livekitServiceUrl = extractLivekitServiceUrl(event) ?? deps.fallbackLivekitServiceUrl;
      if (!livekitServiceUrl) {
        app.log.warn({ roomId: event.room_id }, "call.member event missing livekit_service_url and no fallback");
        return;
      }

      try {
        await ensureVoipBridge({
          voipServiceUrl: deps.voipServiceUrl,
          roomId: event.room_id,
          spiritUserId,
          agentId,
          livekitServiceUrl,
        });
      } catch (err) {
        app.log.warn(
          { roomId: event.room_id, err: String((err as Error)?.message ?? err) },
          "voip_service ensure failed",
        );
      }
    }

    async function handleSpiritMessage(params: {
      event: MatrixRoomMessageEvent;
      spiritUserId: string;
      spiritUserPrefix: string;
      client: MatrixClient;
      agentsBaseUrl: string;
    }): Promise<void> {
      const agentId = parseAgentIdFromSpiritUserId(params.spiritUserId, params.spiritUserPrefix);
      if (!agentId) {
        app.log.warn({ spiritUserId: params.spiritUserId }, "cannot map spirit user id to agent_id");
        return;
      }

      const editor = await startStreamingMessage({
        client: params.client,
        roomId: params.event.room_id,
        userId: params.spiritUserId,
        initial: renderCitedMessage("", []),
        placeholderBody: "…",
      });

      try {
        const live = await createLiveSession({
          agentsBaseUrl: params.agentsBaseUrl,
          agentId,
          platform: "matrix",
          roomId: params.event.room_id,
          initiatorPlatformUserId: params.event.sender,
          modality: "text",
        });

        const result = await runLiveTurn({
          agentsWsUrl: live.ws_url,
          prompt: params.event.content.body,
          onDelta: async (delta) => editor.pushDelta(delta),
        });

        await editor.finalize(renderCitedMessage(result.text, result.citations));
      } catch (err) {
        app.log.warn({ err }, "live session failed; falling back to /turn");
        try {
          const result = await callTurnFallback({
            agentsBaseUrl: params.agentsBaseUrl,
            agentId,
            platform: "matrix",
            roomId: params.event.room_id,
            eventId: null,
            senderPlatformUserId: params.event.sender,
            text: params.event.content.body,
            mentions: [],
          });
          await editor.finalize(renderCitedMessage(result.text, result.citations));
        } catch (fallbackErr) {
          app.log.error({ fallbackErr }, "agent turn failed");
          await editor.interrupt("cancelled");
        }
      }
    }

    app.put("/_matrix/app/v1/transactions/:txnId", async (request, reply) => {
      await handleTxn(request.body);
      await reply.code(200).send({});
    });
    app.post("/_matrix/app/v1/transactions/:txnId", async (request, reply) => {
      await handleTxn(request.body);
      await reply.code(200).send({});
    });
  };
  return plugin;
};
