import Constants from "expo-constants";

// `app.config.ts` puts EXPO_PUBLIC_API_URL into `extra.apiUrl`. Debug builds fall back to the local backend
// (`make start-api-local`); a release build without it would call relative URLs, so it fails at load instead.
const DEBUG_API_URL = "http://localhost:8000";

function resolveApiUrl(): string {
  const configured = Constants.expoConfig?.extra?.apiUrl as string | undefined;
  if (configured) return configured;
  if (__DEV__) return DEBUG_API_URL;
  throw new Error("EXPO_PUBLIC_API_URL is not set: release builds need the API URL (see app.config.ts extra.apiUrl)");
}

export const API_URL: string = resolveApiUrl();

export class UnauthorizedError extends Error {}
// A 4xx other than 401: the server understood the request and refused it, so retrying it unchanged cannot help.
export class ClientError extends Error {}
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
  if (!response.ok) throw new ClientError(`${response.status} from ${path}`);

  return response.status === 204 ? null : response.json();
}

async function fetchOrThrow(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (error) {
    throw new NetworkError(String(error));
  }
}
