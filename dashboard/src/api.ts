import { useCallback, useEffect, useState } from 'react';

const TOKEN_KEY = 'viber.token';
const UNAUTHORIZED_EVENT = 'viber:unauthorized';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string {
  try { return localStorage.getItem(TOKEN_KEY) ?? ''; } catch { return ''; }
}

export function setToken(token: string): void {
  try { localStorage.setItem(TOKEN_KEY, token); } catch { /* a blocked store only costs re-entering it */ }
}

export function onUnauthorized(listener: () => void): () => void {
  window.addEventListener(UNAUTHORIZED_EVENT, listener);
  return () => window.removeEventListener(UNAUTHORIZED_EVENT, listener);
}

function describe(detail: unknown): string {
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'error' in detail) return String((detail as { error: unknown }).error);
  return JSON.stringify(detail);
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('X-Viber-Actor', 'dashboard');
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError(401, 'This Viber needs an access token.');
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try { message = describe((await response.json()).detail ?? message); } catch { /* keep the status line */ }
    throw new ApiError(response.status, message);
  }
  const type = response.headers.get('content-type') ?? '';
  return (type.includes('json') ? response.json() : response.text()) as Promise<T>;
}

export const post = <T>(path: string, body?: unknown) =>
  apiFetch<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });

interface ApiState<T> { data: T | null; error: string | null; loading: boolean }

/** Reads `path` (null skips), re-reads on reload() and, if asked, on an interval. Keeps the last data while refreshing. */
export function useApi<T>(path: string | null, refreshMs = 0) {
  const [state, setState] = useState<ApiState<T>>({ data: null, error: null, loading: path !== null });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (path === null) return undefined;
    let cancelled = false;
    apiFetch<T>(path)
      .then((data) => { if (!cancelled) setState({ data, error: null, loading: false }); })
      .catch((error: Error) => { if (!cancelled) setState((held) => ({ data: held.data, error: error.message, loading: false })); });
    return () => { cancelled = true; };
  }, [path, tick]);

  useEffect(() => {
    if (!refreshMs) return undefined;
    const timer = window.setInterval(() => setTick((count) => count + 1), refreshMs);
    return () => window.clearInterval(timer);
  }, [refreshMs]);

  const reload = useCallback(() => setTick((count) => count + 1), []);
  return { ...state, reload };
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '-';
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86400)} d ago`;
}
