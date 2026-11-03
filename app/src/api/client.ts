// Debug builds talk to the local backend (`make start-api-local`) unless overridden.
export const API_URL: string =
  process.env.EXPO_PUBLIC_API_URL ?? (__DEV__ ? "http://localhost:8000" : "");

export class UnauthorizedError extends Error {}
export class NetworkError extends Error {}

type FetchInit = { method?: string; body?: unknown; sessionKey: string | null };

export async function apiFetch(path: string, init: FetchInit): Promise<unknown> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (init.sessionKey) headers.Authorization = `Bearer ${init.sessionKey}`;

  const response = await fetchOrThrow(`${API_URL}${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });

  if (response.status === 401) throw new UnauthorizedError(`401 from ${path}`);
  if (response.status >= 500) throw new NetworkError(`${response.status} from ${path}`);
  if (!response.ok) throw new Error(`${response.status} from ${path}`);

  return response.status === 204 ? null : response.json();
}

async function fetchOrThrow(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (error) {
    throw new NetworkError(String(error));
  }
}
