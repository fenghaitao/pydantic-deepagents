const BASE = process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://localhost:8001';
export const API = `${BASE}/api/v1`;
export const USER_ID = process.env.NEXT_PUBLIC_USER_ID ?? 'local-dev-user';

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

