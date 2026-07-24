import type { DayDiagram, DaySummary } from '../shared/types';

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(body.error ?? 'Request failed');
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

export const api = {
  list: () => request<DaySummary[]>('/api/days'),
  get: (id: string) => request<DayDiagram>(`/api/days/${encodeURIComponent(id)}`),
  create: (name: string) => request<DayDiagram>('/api/days', { method: 'POST', body: JSON.stringify({ name }) }),
  save: (day: DayDiagram) => request<DayDiagram>(`/api/days/${encodeURIComponent(day.id)}`, { method: 'PUT', body: JSON.stringify(day) }),
  delete: (id: string) => request<void>(`/api/days/${encodeURIComponent(id)}`, { method: 'DELETE' })
};
