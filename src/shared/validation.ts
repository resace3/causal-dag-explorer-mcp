import { z } from 'zod';
import { hasDirectedCycle } from './graph.js';

export const nodeSchema = z.object({
  id: z.string().trim().min(1).max(100),
  label: z.string().trim().min(1).max(120),
  x: z.number().finite(),
  y: z.number().finite(),
  sourceEntityId: z.string().trim().min(1).max(255).optional(),
  observedSummary: z.string().trim().min(1).max(500).optional(),
  color: z.enum(['blue', 'green', 'violet', 'orange', 'rose', 'slate']).optional(),
  icon: z.string().trim().min(1).max(8).optional()
});

export const edgeSchema = z.object({
  id: z.string().trim().min(1).max(100),
  source: z.string().trim().min(1).max(100),
  target: z.string().trim().min(1).max(100),
  sourceHandle: z.enum(['left', 'top', 'right', 'bottom']).optional(),
  targetHandle: z.enum(['left', 'top', 'right', 'bottom']).optional(),
  rationale: z.string().trim().min(1).max(500).optional()
});

export const dailyEvidencePointSchema = z.object({
  label: z.string().trim().min(1).max(40),
  sourceValue: z.number().finite(),
  targetValue: z.number().finite(),
  support: z.enum(['supportive', 'not_supportive', 'mixed'])
});

export const hourlyEvidencePointSchema = z.object({
  label: z.string().trim().min(1).max(40),
  sourceValue: z.number().finite(),
  targetValue: z.number().finite()
});

export const relationshipEvidenceSchema = z.object({
  edgeId: z.string().trim().min(1).max(100),
  summary: z.string().trim().min(1).max(500),
  supportCount: z.number().int().min(0).max(365).optional(),
  totalCount: z.number().int().min(1).max(365).optional(),
  averageLag: z.string().trim().min(1).max(80).optional(),
  strengthLabel: z.enum(['Exploratory', 'Weak', 'Moderate', 'Strong']).optional(),
  consistencyLabel: z.string().trim().min(1).max(120).optional(),
  interpretation: z.string().trim().min(1).max(500).optional(),
  sourceUnit: z.string().trim().min(1).max(40).optional(),
  targetUnit: z.string().trim().min(1).max(40).optional(),
  daily: z.array(dailyEvidencePointSchema).max(90).optional(),
  hourly: z.array(hourlyEvidencePointSchema).max(48).optional()
}).superRefine((relationship, ctx) => {
  if (relationship.supportCount !== undefined && relationship.totalCount !== undefined && relationship.supportCount > relationship.totalCount) {
    ctx.addIssue({ code: 'custom', message: 'supportCount cannot exceed totalCount' });
  }
});

export const evidenceSchema = z.object({
  provider: z.enum(['ha_unofficial_ai', 'synthetic_example']),
  question: z.string().trim().min(1).max(500),
  generatedAt: z.string().datetime(),
  entityIds: z.array(z.string().trim().min(1).max(255)).max(100),
  notes: z.array(z.string().trim().min(1).max(500)).max(50),
  windowLabel: z.string().trim().min(1).max(120).optional(),
  relationships: z.array(relationshipEvidenceSchema).max(500).optional()
});

export const daySchema = z.object({
  id: z.string().trim().min(1).max(100),
  name: z.string().trim().min(1).max(100),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
  nodes: z.array(nodeSchema).max(1000),
  edges: z.array(edgeSchema).max(5000),
  evidence: evidenceSchema.optional()
}).superRefine((day, ctx) => {
  const nodeIds = new Set<string>();
  for (const node of day.nodes) {
    if (nodeIds.has(node.id)) ctx.addIssue({ code: 'custom', message: `Duplicate node id: ${node.id}` });
    nodeIds.add(node.id);
  }
  const edgeIds = new Set<string>();
  const pairs = new Set<string>();
  for (const edge of day.edges) {
    if (edgeIds.has(edge.id)) ctx.addIssue({ code: 'custom', message: `Duplicate edge id: ${edge.id}` });
    edgeIds.add(edge.id);
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) ctx.addIssue({ code: 'custom', message: `Edge ${edge.id} has a missing endpoint` });
    if (edge.source === edge.target) ctx.addIssue({ code: 'custom', message: `Self-edge is not allowed: ${edge.source}` });
    const pair = `${edge.source}\u0000${edge.target}`;
    if (pairs.has(pair)) ctx.addIssue({ code: 'custom', message: `Duplicate edge: ${edge.source} -> ${edge.target}` });
    pairs.add(pair);
  }
  if (hasDirectedCycle(nodeIds, day.edges)) ctx.addIssue({ code: 'custom', message: 'Directed cycles are not allowed' });
  const edgeIdSet = new Set(day.edges.map((edge) => edge.id));
  for (const relationship of day.evidence?.relationships ?? []) {
    if (!edgeIdSet.has(relationship.edgeId)) {
      ctx.addIssue({ code: 'custom', message: `Relationship evidence refers to a missing edge: ${relationship.edgeId}` });
    }
  }
});

export const createDaySchema = z.object({ name: z.string().trim().min(1).max(100) });
export const updateDiagramSchema = z.object({ nodes: z.array(nodeSchema).max(1000), edges: z.array(edgeSchema).max(5000) });

export function formatValidationError(error: z.ZodError): string {
  return error.issues.map((issue) => `${issue.path.join('.') || 'day'}: ${issue.message}`).join('; ');
}
