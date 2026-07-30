/**
 * Mirrors `server/app/models/timeline.py`. Keep the two in sync.
 * All timestamps are ISO 8601 with an offset; they are converted to the
 * configured local timezone only when formatted for display.
 */

export type EventType = 'point' | 'interval' | 'continuous';
export type Origin = 'measured' | 'derived';
export type DataQuality = 'high' | 'medium' | 'low' | 'unknown';

export interface Provenance {
  rawRecordIds: string[];
  sourceEntityIds: string[];
  transformationRule?: string | null;
  ruleVersion?: string | null;
  thresholds: Record<string, unknown>;
  inputTimeRange?: string[] | null;
  outputTimestamp?: string | null;
  missingDataAssumptions: string[];
  notes: string[];
}

export interface TimelineEvent {
  id: string;
  phenotype: string;
  label: string;
  eventType: EventType;
  startTime: string;
  endTime?: string | null;
  value?: number | string | null;
  unit?: string | null;
  source: string;
  device?: string | null;
  entityId?: string | null;
  measuredOrDerived: Origin;
  confidence?: number | null;
  dataQuality: DataQuality;
  category?: string | null;
  continuesBefore: boolean;
  continuesAfter: boolean;
  metadata: Record<string, unknown>;
  provenance?: Provenance | null;
}

export interface SeriesPoint {
  timestamp: string;
  value: number;
  quality?: number | null;
}

export interface SeriesGap {
  startTime: string;
  endTime: string;
  reason?: string | null;
}

export interface TimelineSeries {
  id: string;
  phenotype: string;
  label: string;
  unit: string;
  source: string;
  device?: string | null;
  entityId?: string | null;
  measuredOrDerived: Origin;
  points: SeriesPoint[];
  gaps: SeriesGap[];
  minValue?: number | null;
  maxValue?: number | null;
  style: 'primary' | 'secondary';
  metadata: Record<string, unknown>;
  provenance?: Provenance | null;
}

export type AccentToken =
  | 'green'
  | 'blue'
  | 'indigo'
  | 'purple'
  | 'orange'
  | 'teal'
  | 'sky'
  | 'cyan';

export interface Lane {
  id: string;
  phenotype: string;
  label: string;
  description: string;
  accent: AccentToken;
  available: boolean;
  unavailableReason?: string | null;
  units: string[];
  events: TimelineEvent[];
  series: TimelineSeries[];
  sources: string[];
}

export interface CoverageWindow {
  startTime: string;
  endTime: string;
  label: string;
}

export interface DayCoverage {
  overallFraction: number;
  perLane: Record<string, number>;
  missingPeriods: CoverageWindow[];
}

export interface SyncSummary {
  dateProcessed: string;
  localTimezone: string;
  dayStart: string;
  dayEnd: string;
  dayLengthHours: number;
  sourcesChecked: string[];
  rawRecordCount: number;
  normalizedEventCount: number;
  derivedFeatureCount: number;
  seriesPointCount: number;
  coverage: DayCoverage;
  warnings: string[];
  errors: string[];
  startedAt?: string | null;
  completedAt?: string | null;
}

export interface DayTimeline {
  date: string;
  localTimezone: string;
  dayStart: string;
  dayEnd: string;
  dayLengthHours: number;
  generatedAt: string;
  lanes: Lane[];
  summary: SyncSummary;
  highlights: string[];
  mockData: boolean;
}

export type SourceStatus =
  | 'connected'
  | 'disconnected'
  | 'syncing'
  | 'error'
  | 'mock_data';

export type SourceTransport = 'mcp' | 'rest' | 'mock' | 'file';

export interface DataSource {
  id: string;
  name: string;
  status: SourceStatus;
  /** The MCP server this source corresponds to, as named in the MCP client. */
  mcpServer?: string | null;
  transport: SourceTransport;
  provider?: string | null;
  capabilities: string[];
  detail?: string | null;
  lastSync?: string | null;
  entityCount?: number | null;
  /** False when the source answered but had nothing for the displayed day. */
  hasData: boolean;
  /** False when switched off, in which case it was never contacted. */
  selected: boolean;
  /** Position in the merge order; lower wins when two sources share a metric. */
  priority: number | null;
}

export interface DataSourceReport {
  sources: DataSource[];
  mockData: boolean;
  checkedAt?: string | null;
}

export interface EventDetailsResponse {
  event: TimelineEvent;
  laneId: string;
  date: string;
  rawRecordCount: number;
  rawRecords: RawRecordSummary[];
}

export interface RawRecordSummary {
  id: string;
  source: string;
  stream: string;
  entityId?: string | null;
  device?: string | null;
  timestamp: string;
  endTimestamp?: string | null;
  value?: number | string | null;
  unit?: string | null;
}

/** A single sample the user clicked on a continuous line. */
export interface SeriesSelection {
  kind: 'series-point';
  laneId: string;
  series: TimelineSeries;
  point: SeriesPoint;
}

export interface EventSelection {
  kind: 'event';
  laneId: string;
  event: TimelineEvent;
}

export type Selection = EventSelection | SeriesSelection;

export function selectionKey(selection: Selection): string {
  return selection.kind === 'event'
    ? `event:${selection.event.id}`
    : `point:${selection.series.id}:${selection.point.timestamp}`;
}
