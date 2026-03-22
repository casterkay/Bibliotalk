function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function mustString(obj, key) {
  const value = obj[key];
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`Invalid request: missing ${key}`);
  }
  return value.trim();
}

function optionalString(obj, key) {
  const value = obj[key];
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export function parseEnsureRequest(raw) {
  if (!isRecord(raw)) throw new Error("Invalid request: body must be an object");
  return {
    room_id: mustString(raw, "room_id"),
    spirit_user_id: mustString(raw, "spirit_user_id"),
    agent_id: mustString(raw, "agent_id"),
    livekit_service_url: optionalString(raw, "livekit_service_url"),
  };
}

export function parseStopRequest(raw) {
  if (raw == null) {
    return { room_id: null, reason: "requested" };
  }
  if (!isRecord(raw)) throw new Error("Invalid request: body must be an object");
  return {
    room_id: optionalString(raw, "room_id"),
    reason: optionalString(raw, "reason") ?? "requested",
  };
}
