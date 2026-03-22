import type { MatrixCallMemberEvent } from "../matrix/events.js";

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function extractLivekitServiceUrl(event: MatrixCallMemberEvent): string | null {
  const content = asRecord(event.content);
  if (!content) return null;

  const foci = content.foci_preferred;
  if (!Array.isArray(foci)) return null;

  for (const raw of foci) {
    const focus = asRecord(raw);
    if (!focus) continue;
    const type = focus.type;
    const url = focus.livekit_service_url;
    if (type === "livekit" && typeof url === "string" && url.trim()) {
      return url.trim();
    }
    if (typeof url === "string" && url.trim()) {
      return url.trim();
    }
  }
  return null;
}
