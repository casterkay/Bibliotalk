import { randomUUID } from "node:crypto";

import { httpJson } from "./http_utils.js";

function withTrailingSlash(url) {
  return url.endsWith("/") ? url : `${url}/`;
}

function buildUrl(baseUrl, path, query) {
  const url = new URL(path.replace(/^[\\/]+/, ""), withTrailingSlash(baseUrl));
  for (const [k, v] of Object.entries(query)) {
    if (v) url.searchParams.set(k, v);
  }
  return url.toString();
}

export class MatrixAsClient {
  constructor(config) {
    this._homeserverUrl = config.homeserverUrl;
    this._asToken = config.asToken;
  }

  async requestOpenIdToken(userId) {
    const url = buildUrl(
      this._homeserverUrl,
      `/_matrix/client/v3/user/${encodeURIComponent(userId)}/openid/request_token`,
      { access_token: this._asToken, user_id: userId },
    );
    return await httpJson("POST", url, {});
  }

  async sendNotice(roomId, userId, text) {
    const txnId = randomUUID();
    const url = buildUrl(
      this._homeserverUrl,
      `/_matrix/client/v3/rooms/${encodeURIComponent(roomId)}/send/m.room.message/${encodeURIComponent(txnId)}`,
      { access_token: this._asToken, user_id: userId },
    );
    await httpJson("PUT", url, { msgtype: "m.notice", body: text });
  }
}
