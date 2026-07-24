export interface DayNode {
  id: string;
  label: string;
  x: number;
  y: number;
  sourceEntityId?: string;
  observedSummary?: string;
  color?: 'blue' | 'green' | 'violet' | 'orange' | 'rose' | 'slate';
  icon?: string;
}

export interface DayEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
  rationale?: string;
}

export type EvidenceSupport = 'supportive' | 'not_supportive' | 'mixed';

export interface DailyEvidencePoint {
  label: string;
  sourceValue: number;
  targetValue: number;
  support: EvidenceSupport;
}

export interface HourlyEvidencePoint {
  label: string;
  sourceValue: number;
  targetValue: number;
}

export interface RelationshipEvidence {
  edgeId: string;
  summary: string;
  supportCount?: number;
  totalCount?: number;
  averageLag?: string;
  strengthLabel?: 'Exploratory' | 'Weak' | 'Moderate' | 'Strong';
  consistencyLabel?: string;
  interpretation?: string;
  sourceUnit?: string;
  targetUnit?: string;
  daily?: DailyEvidencePoint[];
  hourly?: HourlyEvidencePoint[];
}

export interface DiagramEvidence {
  provider: 'ha_unofficial_ai' | 'synthetic_example';
  question: string;
  generatedAt: string;
  entityIds: string[];
  notes: string[];
  windowLabel?: string;
  relationships?: RelationshipEvidence[];
}

export interface DayDiagram {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  nodes: DayNode[];
  edges: DayEdge[];
  evidence?: DiagramEvidence;
}

export interface DaySummary {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
}
