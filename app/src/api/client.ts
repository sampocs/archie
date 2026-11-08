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
export class ClientError extends Error {
  constructor(
    message: string,
    readonly status: number | null = null,
  ) {
    super(message);
  }
}
export class NetworkError extends Error {}

type FetchInit = { method?: string; body?: unknown; sessionKey: string | null; signal?: AbortSignal };

export async function apiFetch(path: string, init: FetchInit): Promise<unknown> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (init.sessionKey) headers.Authorization = `Bearer ${init.sessionKey}`;

  const response = await fetchOrThrow(`${API_URL}${path}`, {
    method: init.method ?? "GET",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
    signal: init.signal,
  });
  return responseBody(response, path);
}

/** A multipart POST (e.g. recorded audio); fetch sets the multipart content type and boundary itself. */
export async function apiUpload(
  path: string,
  init: { form: FormData; sessionKey: string | null; signal?: AbortSignal },
): Promise<unknown> {
  const headers: Record<string, string> = {};
  if (init.sessionKey) headers.Authorization = `Bearer ${init.sessionKey}`;
  const response = await fetchOrThrow(`${API_URL}${path}`, { method: "POST", headers, body: init.form, signal: init.signal });
  return responseBody(response, path);
}

async function responseBody(response: Response, path: string): Promise<unknown> {
  if (response.status === 401) throw new UnauthorizedError(`401 from ${path}`);
  if (response.status >= 500) throw new NetworkError(`${response.status} from ${path}`);
  if (!response.ok) throw new ClientError(`${response.status} from ${path}`, response.status);

  return response.status === 204 ? null : response.json();
}

// An aborted fetch rejects here too, so a cancelled call surfaces as NetworkError.
async function fetchOrThrow(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (error) {
    throw new NetworkError(String(error));
  }
}
