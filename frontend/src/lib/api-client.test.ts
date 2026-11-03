import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiBlob, apiJson, errorMessage, parseError, workspaceToken } from './api-client';

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });

describe('workspace token', () => {
  beforeEach(() => localStorage.clear());

  it('is created once, URL-safe, and reused', () => {
    const first = workspaceToken();
    expect(first).toMatch(/^[A-Za-z0-9_-]{32,128}$/); // the format the backend accepts
    expect(workspaceToken()).toBe(first);
    expect(localStorage.getItem('documind-workspace-token')).toBe(first);
  });
});

describe('apiJson', () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    localStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('sends the workspace token, JSON body and query parameters', async () => {
    fetchMock.mockResolvedValue(json({ ok: true }));
    await apiJson('/documents', { method: 'PATCH', json: { a: 1 }, query: { status: ['FAILED', 'OCR'], q: '', limit: 5 } });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/documents?status=FAILED&status=OCR&limit=5'); // empty values are dropped
    expect(init.method).toBe('PATCH');
    expect(init.headers['X-Workspace-Token']).toBe(workspaceToken());
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(init.body).toBe('{"a":1}');
  });

  it('returns undefined for 204 No Content', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(apiJson('/documents/1', { method: 'DELETE' })).resolves.toBeUndefined();
  });

  it('turns the backend error envelope into an ApiError with code, details and request id', async () => {
    fetchMock.mockResolvedValue(
      json({ error: { code: 'duplicate_document', message: 'Already there.', details: { existing_document_id: 'x' } } }, 409, { 'X-Request-ID': 'req-1' }),
    );
    const error = (await apiJson('/documents/upload').catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect([error.status, error.code, error.message, error.requestId]).toEqual([409, 'duplicate_document', 'Already there.', 'req-1']);
    expect(error.details).toEqual({ existing_document_id: 'x' });
  });

  it('reports network failures and timeouts in plain language', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(apiJson('/health')).rejects.toMatchObject({ code: 'network_error' });

    fetchMock.mockImplementation((_url, init) => new Promise((_, reject) => init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))));
    await expect(apiJson('/health', { timeoutMs: 10 })).rejects.toMatchObject({ code: 'timeout' });
  });

  it('reads the download filename from Content-Disposition (UTF-8 form preferred)', async () => {
    fetchMock.mockResolvedValue(new Response('pdf', { headers: { 'Content-Disposition': `inline; filename="a_b.pdf"; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf` } }));
    const { filename } = await apiBlob('/documents/1/file');
    expect(filename).toBe('résumé.pdf');
  });
});

describe('errors', () => {
  it('falls back to a generic message for non-envelope responses', () => {
    expect(parseError(502, '<html>').code).toBe('http_error');
    expect(errorMessage(new Error('internal detail'))).toBe('Something went wrong. Please try again.');
  });
});
