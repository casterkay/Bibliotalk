import { buildServer } from "./server.js";

async function main() {
  const app = await buildServer();

  const portRaw = process.env.VOIP_SERVICE_PORT || process.env.PORT || "9012";
  const port = Number(portRaw);
  if (!Number.isFinite(port)) {
    throw new Error(`Invalid VOIP_SERVICE_PORT: ${portRaw}`);
  }

  const host = process.env.VOIP_SERVICE_HOST || "0.0.0.0";
  await app.listen({ host, port });
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error("voip_service failed", err);
  process.exit(1);
});
