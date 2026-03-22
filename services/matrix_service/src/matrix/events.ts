export type MatrixEventType = "m.room.message" | "m.room.member" | "org.matrix.msc3401.call.member";

export type MatrixTransaction = {
  events: MatrixEvent[];
};

export type MatrixEventBase = {
  type: MatrixEventType;
  room_id: string;
  sender: string;
};

export type MatrixMentions = {
  user_ids?: string[];
};

export type MatrixMessageContent = {
  msgtype: "m.text" | "m.notice" | string;
  body: string;
  "m.mentions"?: MatrixMentions;
  "m.relates_to"?: { rel_type?: string };
};

export type MatrixRoomMessageEvent = MatrixEventBase & {
  type: "m.room.message";
  content: MatrixMessageContent;
};

export type MatrixRoomMemberEvent = MatrixEventBase & {
  type: "m.room.member";
  state_key: string;
  content: { membership: "invite" | "join" | "leave" | "ban" | string };
};

export type MatrixCallMemberEvent = MatrixEventBase & {
  type: "org.matrix.msc3401.call.member";
  state_key: string;
  content: Record<string, unknown>;
};

export type MatrixEvent = MatrixRoomMessageEvent | MatrixRoomMemberEvent | MatrixCallMemberEvent;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseTransaction(body: unknown): MatrixTransaction {
  if (!isRecord(body)) return { events: [] };
  const rawEvents = body.events;
  if (!Array.isArray(rawEvents)) return { events: [] };

  const events: MatrixEvent[] = [];
  for (const raw of rawEvents) {
    const parsed = parseEvent(raw);
    if (parsed) events.push(parsed);
  }
  return { events };
}

export function parseEvent(raw: unknown): MatrixEvent | null {
  if (!isRecord(raw)) return null;
  const type = raw.type;
  const room_id = raw.room_id;
  const sender = raw.sender;
  if (typeof type !== "string" || typeof room_id !== "string" || typeof sender !== "string") return null;

  if (type === "m.room.message") {
    const content = raw.content;
    if (!isRecord(content)) return null;
    if (typeof content.body !== "string") return null;
    if (typeof content.msgtype !== "string") return null;
    return { type, room_id, sender, content: content as MatrixMessageContent };
  }

  if (type === "m.room.member") {
    const state_key = raw.state_key;
    const content = raw.content;
    if (typeof state_key !== "string" || !isRecord(content)) return null;
    const membership = content.membership;
    if (typeof membership !== "string") return null;
    return { type, room_id, sender, state_key, content: { membership } };
  }

  if (type === "org.matrix.msc3401.call.member") {
    const state_key = raw.state_key;
    const content = raw.content;
    if (typeof state_key !== "string" || !isRecord(content)) return null;
    return { type, room_id, sender, state_key, content };
  }

  return null;
}
