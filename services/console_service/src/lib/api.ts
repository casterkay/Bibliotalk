export type ApiError = { status: number; detail: string };

async function parseError(resp: Response): Promise<ApiError> {
  let detail = resp.statusText;
  try {
    const json = await resp.json();
    detail = json?.detail ? String(json.detail) : JSON.stringify(json);
  } catch {
    try {
      detail = await resp.text();
    } catch {
      // ignore
    }
  }
  return { status: resp.status, detail };
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(path, { credentials: "include" });
  if (!resp.ok) throw await parseError(resp);
  return (await resp.json()) as T;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw await parseError(resp);
  return (await resp.json()) as T;
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw await parseError(resp);
  return (await resp.json()) as T;
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw await parseError(resp);
  return (await resp.json()) as T;
}

export async function apiDelete<T>(path: string): Promise<T> {
  const resp = await fetch(path, { method: "DELETE", credentials: "include" });
  if (!resp.ok) throw await parseError(resp);
  return (await resp.json()) as T;
}
