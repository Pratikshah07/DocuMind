/**
 * Central HTTP client for the DocuMind API.
 *
 * - Base URL: VITE_API_BASE_URL (empty = same origin; the dev server proxies /api).
 * - Every request carries this browser's anonymous workspace token (X-Workspace-Token).
 *   The backend scopes all documents to it, so visitors never see each other's uploads.
 * - Errors are normalised from the backend envelope {error: {code, message, details}, request_id}.
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
const TOKEN_KEY = 'documind-workspace-token';
const DEFAULT_TIMEOUT_MS = 30_000;

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
    public requestId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

let memoryToken: string | null = null;

function randomToken(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** The browser's private workspace token, created on first use. */
export function workspaceToken(): string {
  try {
    let token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      token = randomToken();
      localStorage.setItem(TOKEN_KEY, token);
    }
    return token;
  } catch {
    // Storage blocked (private mode): keep a token for this tab only.
    memoryToken ??= randomToken();
    return memoryToken;
  }
}

export function parseError(status: number, body: unknown, requestId?: string | null): ApiError {
  const error = (body as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error;
  if (error?.code) return new ApiError(status, error.code, error.message ?? 'Request failed.', error.details, requestId ?? undefined);
  if (status === 0) return new ApiError(0, 'network_error', 'Cannot reach the DocuMind server. Check your connection and try again.');
  return new ApiError(status, 'http_error', `The server returned an unexpected error (${status}).`, undefined, requestId ?? undefined);
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  json?: unknown;
  body?: BodyInit;
  query?: Record<string, string | number | string[] | undefined | null>;
  timeoutMs?: number;
  signal?: AbortSignal;
};

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === '') continue;
    for (const item of Array.isArray(value) ? value : [value]) params.append(key, String(item));
  }
  const qs = params.toString();
  return `${BASE_URL}/api${path}${qs ? `?${qs}` : ''}`;
}

async function send(path: string, options: RequestOptions = {}): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  options.signal?.addEventListener('abort', () => controller.abort());
  const headers: Record<string, string> = { 'X-Workspace-Token': workspaceToken() };
  let body = options.body;
  if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.json);
  }
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), { method: options.method ?? 'GET', headers, body, signal: controller.signal });
  } catch {
    if (controller.signal.aborted && !options.signal?.aborted) {
      throw new ApiError(0, 'timeout', 'The server took too long to respond. Please try again.');
    }
    throw parseError(0, null);
  } finally {
    window.clearTimeout(timer);
  }
  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      /* non-JSON error body */
    }
    throw parseError(response.status, payload, response.headers.get('X-Request-ID'));
  }
  return response;
}

export async function apiJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await send(path, options);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiBlob(path: string, options: RequestOptions = {}): Promise<{ blob: Blob; filename: string | null }> {
  const response = await send(path, options);
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
  const plain = /filename="([^"]+)"/i.exec(disposition)?.[1];
  return { blob: await response.blob(), filename: utf8 ? decodeURIComponent(utf8) : plain ?? null };
}

/** User-facing message for any thrown value. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return 'Something went wrong. Please try again.';
}
