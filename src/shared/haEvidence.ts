import { z } from 'zod';
import type { DayEdge, DayNode, DiagramEvidence } from './types.js';
import { relationshipEvidenceSchema } from './validation.js';

const handleSchema = z.enum(['left', 'top', 'right', 'bottom']);

export const haEvidenceDagInputSchema = z.object({
  name: z.string().trim().min(1).max(100),
  question: z.string().trim().min(1).max(500),
  nodes: z.array(z.object({
    id: z.string().trim().min(1).max(100),
    label: z.string().trim().min(1).max(120),
    entity_id: z.string().trim().min(1).max(255).optional(),
    observed_summary: z.string().trim().min(1).max(500).optional(),
    color: z.enum(['blue', 'green', 'violet', 'orange', 'rose', 'slate']).optional(),
    icon: z.string().trim().min(1).max(8).optional(),
    x: z.number().finite().optional(),
    y: z.number().finite().optional()
  })).min(1).max(100),
  edges: z.array(z.object({
    id: z.string().trim().min(1).max(100).optional(),
    source: z.string().trim().min(1).max(100),
    target: z.string().trim().min(1).max(100),
    source_handle: handleSchema.optional(),
    target_handle: handleSchema.optional(),
    rationale: z.string().trim().min(1).max(500).optional()
  })).max(500),
  evidence_notes: z.array(z.string().trim().min(1).max(500)).max(50).default([]),
  window_label: z.string().trim().min(1).max(120).optional(),
  relationship_evidence: z.array(relationshipEvidenceSchema).max(500).optional()
});

export type HaEvidenceDagInput = z.infer<typeof haEvidenceDagInputSchema>;

export function buildHaEvidenceDiagram(input: HaEvidenceDagInput): { nodes: DayNode[]; edges: DayEdge[]; evidence: DiagramEvidence } {
  const nodes = input.nodes.map((node, index): DayNode => ({
    id: node.id,
    label: node.label,
    x: node.x ?? 100 + (index % 3) * 250,
    y: node.y ?? 100 + Math.floor(index / 3) * 180,
    ...(node.entity_id ? { sourceEntityId: node.entity_id } : {}),
    ...(node.observed_summary ? { observedSummary: node.observed_summary } : {}),
    ...(node.color ? { color: node.color } : {}),
    ...(node.icon ? { icon: node.icon } : {})
  }));
  const edges = input.edges.map((edge, index): DayEdge => ({
    id: edge.id ?? `edge-ha-${index + 1}`,
    source: edge.source,
    target: edge.target,
    ...(edge.source_handle ? { sourceHandle: edge.source_handle } : {}),
    ...(edge.target_handle ? { targetHandle: edge.target_handle } : {}),
    ...(edge.rationale ? { rationale: edge.rationale } : {})
  }));
  const entityIds = [...new Set(nodes.flatMap((node) => node.sourceEntityId ? [node.sourceEntityId] : []))];
  return {
    nodes,
    edges,
    evidence: {
      provider: 'ha_unofficial_ai',
      question: input.question,
      generatedAt: new Date().toISOString(),
      entityIds,
      notes: input.evidence_notes,
      ...(input.window_label ? { windowLabel: input.window_label } : {}),
      ...(input.relationship_evidence ? { relationships: input.relationship_evidence } : {})
    }
  };
}
