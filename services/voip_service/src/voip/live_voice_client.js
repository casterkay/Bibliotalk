import { httpJson } from "./http_utils.js";

function stripTrailingSlash(url) {
  return url.endsWith("/") ? url.slice(0, -1) : url;
}

export class AgentsLiveVoiceClient {
  constructor(config) {
    this._agentsServiceUrl = stripTrailingSlash(config.agentsServiceUrl);
    this._agentId = config.agentId;
    this._platform = config.platform;
    this._roomId = config.roomId;
    this._initiatorPlatformUserId = config.initiatorPlatformUserId;
  }

  async createSession() {
    const url = `${this._agentsServiceUrl}/v1/agents/${this._agentId}/live/sessions`;
    const res = await httpJson("POST", url, {
      platform: this._platform,
      room_id: this._roomId,
      initiator_platform_user_id: this._initiatorPlatformUserId,
      modality: "voice",
    });
    const wsUrl = String(res.ws_url || "");
    const sessionId = String(res.session_id || "");
    if (!wsUrl || !sessionId) {
      throw new Error(`agents_service live session missing ws_url/session_id: ${JSON.stringify(res).slice(0, 2000)}`);
    }
    return { sessionId, wsUrl };
  }
}
