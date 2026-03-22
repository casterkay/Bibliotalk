import fastify from "fastify";

import { BridgeManager } from "./voip/bridge_manager.js";
import { parseEnsureRequest, parseStopRequest } from "./voip/http_models.js";

function env(name, fallback = "") {
  return process.env[name] ?? fallback;
}

export async function buildServer() {
  const app = fastify({ logger: true });

  const manager = new BridgeManager({
    homeserverUrl: env("MATRIX_HOMESERVER_URL", "http://localhost:8008"),
    matrixAsToken: env("MATRIX_AS_TOKEN", ""),
    agentsServiceUrl: env("AGENTS_SERVICE_URL", "http://localhost:8009"),
    fallbackLivekitServiceUrl: env("VOIP_LIVEKIT_SERVICE_URL", ""),
  });

  app.get("/healthz", async () => ({ status: "ok" }));

  app.post("/v1/voip/ensure", async (req, reply) => {
    const body = parseEnsureRequest(req.body);
    const status = await manager.ensure(body);
    return reply.send({ ok: true, status });
  });

  app.post("/v1/voip/stop", async (req, reply) => {
    const body = parseStopRequest(req.body);
    const status = await manager.stop(body);
    return reply.send({ ok: true, status });
  });

  app.addHook("onClose", async () => {
    await manager.stop({ room_id: null, reason: "shutdown" });
  });

  return app;
}
