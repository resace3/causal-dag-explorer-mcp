/** Typed access to the local API. Nothing here talks to a remote host. */

import type {
  DataSourceReport,
  DayTimeline,
  EventDetailsResponse,
  RawRecordSummary,
} from '../types/timeline';

const BASE = (import.meta.env?.VITE_API_BASE_URL as string | undefined) ?? '';

export class ApiError extends Error {
  readonly code: string;
  readonly hint?: string;
  readonly status: number;

  constructor(message: string, code: string, status: number, hint?: string) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.hint = hint;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch (cause) {
    throw new ApiError(
      'The local backend is not reachable. Start it with `make dev`, or run the ' +
        'launch_yesterday_timeline MCP tool.',
      'backend_unreachable',
      0,
      String(cause),
    );
  }

  if (!response.ok) {
    let code = `http_${response.status}`;
    let message = `The local API returned HTTP ${response.status} for ${path}.`;
    let hint: string | undefined;
    try {
      const body = await response.json();
      if (body?.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
        hint = body.error.hint;
      } else if (body?.detail) {
        message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* keep the default message */
    }
    throw new ApiError(message, code, response.status, hint);
  }

  return (await response.json()) as T;
}

export interface AppConfigResponse {
  localTimezone: string;
  yesterday: string;
  dayStart: string;
  dayEnd: string;
  dayLengthHours: number;
  mockData: boolean;
  mockSeed: number | null;
  wearableProvider: string;
  availableWearableProviders: string[];
  homeAssistantConfigured: boolean;
  configPath: string;
  lightThresholds: Record<string, { minLux: number | null; maxLux: number | null }>;
  dataDirectory: string;
}

export interface DayIndex {
  date: string;
  isToday: boolean;
  isYesterday: boolean;
  stored: boolean;
  eventCount: number | null;
  coverage: number | null;
  hasData: boolean;
}

export interface DaysResponse {
  localTimezone: string;
  today: string;
  yesterday: string;
  days: DayIndex[];
}

export interface DagVariable {
  id: string;
  label: string;
  description: string;
  measured: boolean;
  lane: string | null;
  unit: string | null;
  observed: boolean;
}

export interface DagNode extends DagVariable {
  role: string;
  layer: number;
  order: number;
}

export type EdgeOrigin = 'knowledge_base' | 'user';
export type EdgeStrength = 'established' | 'plausible' | 'speculative';

export interface DagEdge {
  source: string;
  target: string;
  rationale: string;
  strength: EdgeStrength;
  lag: string | null;
  onPath: boolean;
  origin: EdgeOrigin;
}

/** A row in the edge editor: every edge in the model, labelled. */
export interface CausalEdgeRow {
  source: string;
  target: string;
  sourceLabel: string;
  targetLabel: string;
  rationale: string;
  strength: EdgeStrength;
  lag: string | null;
  origin: EdgeOrigin;
}

export interface SuppressedEdgeRow {
  source: string;
  target: string;
  sourceLabel: string;
  targetLabel: string;
}

export interface CausalEdgesResponse {
  edges: CausalEdgeRow[];
  suppressed: SuppressedEdgeRow[];
  note: string;
}

/** A variable's row in the time-anchored view. */
export interface DagRow {
  variable: string;
  label: string;
  role: string;
  measured: boolean;
  /** events | continuous | whole_day | absent | unmeasured */
  status: string;
  note: string;
  lane: string | null;
  unit: string | null;
  bandStart: string | null;
  bandEnd: string | null;
}

/** One time-anchored appearance of a variable on the day being viewed. */
export interface DagOccurrence {
  id: string;
  variable: string;
  label: string;
  detail: string;
  start: string;
  end: string | null;
  /** event | reading | span | constant */
  kind: string;
  value: number | string | null;
  unit: string | null;
  eventId: string | null;
}

/** An assumed edge, placed between two things the day actually recorded. */
export interface DagLink {
  source: string;
  target: string;
  sourceVariable: string;
  targetVariable: string;
  kind: 'immediate' | 'delayed';
  lagMinutes: number;
  strength: EdgeStrength;
  rationale: string;
  onPath: boolean;
  origin: EdgeOrigin;
}

export interface DagUnplacedEdge {
  source: string;
  target: string;
  sourceLabel: string;
  targetLabel: string;
  reason: string;
}

export interface DagTimeline {
  dayStart: string;
  dayEnd: string;
  localTimezone: string;
  rows: DagRow[];
  occurrences: DagOccurrence[];
  links: DagLink[];
  unplacedEdges: DagUnplacedEdge[];
}

export interface DagResponse {
  date: string;
  outcome: string;
  exposure: string | null;
  nodes: DagNode[];
  edges: DagEdge[];
  /** Null when the day has not been processed yet. */
  timeline: DagTimeline | null;
  adjustmentSet: string[];
  unmeasuredConfounders: string[];
  mediators: string[];
  colliders: string[];
  notes: string[];
  /** Always false: this app proposes structure, it never estimates effects. */
  estimated: boolean;
  disclaimer: string;
}

export const api = {
  health: () => request<{ status: string; yesterday: string }>('/api/health'),
  config: () => request<AppConfigResponse>('/api/config'),
  dataSources: () => request<DataSourceReport>('/api/data-sources'),
  yesterday: () => request<DayTimeline>('/api/yesterday'),
  days: (span = 60) => request<DaysResponse>(`/api/days?span=${span}`),
  day: (date: string) => request<DayTimeline>(`/api/day/${date}`),
  sync: (date?: string) =>
    request<DayTimeline>(date ? `/api/day/${date}/sync` : '/api/yesterday/sync', {
      method: 'POST',
      body: JSON.stringify({ forceRefresh: true }),
    }),
  dagVariables: (date?: string) =>
    request<{ date: string; variables: DagVariable[] }>(
      `/api/dag/variables${date ? `?day=${date}` : ''}`,
    ),
  dag: (body: { outcome: string; exposure: string | null; day: string | null }) =>
    request<DagResponse>('/api/dag', { method: 'POST', body: JSON.stringify(body) }),
  causalEdges: () => request<CausalEdgesResponse>('/api/dag/edges'),
  addCausalEdge: (body: {
    source: string;
    target: string;
    rationale?: string;
    strength?: EdgeStrength;
  }) => request<unknown>('/api/dag/edges', { method: 'POST', body: JSON.stringify(body) }),
  removeCausalEdge: (source: string, target: string) =>
    request<{ restorable: boolean }>(
      `/api/dag/edges/${encodeURIComponent(source)}/${encodeURIComponent(target)}`,
      { method: 'DELETE' },
    ),
  restoreCausalEdge: (source: string, target: string) =>
    request<unknown>(
      `/api/dag/edges/${encodeURIComponent(source)}/${encodeURIComponent(target)}/restore`,
      { method: 'POST' },
    ),
  eventDetails: (eventId: string) =>
    request<EventDetailsResponse>(`/api/events/${encodeURIComponent(eventId)}`),
  rawRecord: (recordId: string) =>
    request<RawRecordSummary & { attributes: Record<string, unknown> }>(
      `/api/raw-records/${encodeURIComponent(recordId)}`,
    ),
  laneConfig: () => request<{ lanes: Record<string, boolean> }>('/api/lane-config'),
  updateLaneConfig: (lanes: Record<string, boolean>) =>
    request<{ lanes: Record<string, boolean> }>('/api/lane-config', {
      method: 'PATCH',
      body: JSON.stringify({ lanes }),
    }),
};
