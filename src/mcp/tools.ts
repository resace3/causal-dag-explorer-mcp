const handle = { type: 'string', enum: ['left', 'top', 'right', 'bottom'] };
const node = {
  type: 'object',
  additionalProperties: false,
  properties: {
    id: { type: 'string', minLength: 1, maxLength: 100 },
    label: { type: 'string', minLength: 1, maxLength: 120 },
    x: { type: 'number' },
    y: { type: 'number' },
    sourceEntityId: { type: 'string', minLength: 1, maxLength: 255 },
    observedSummary: { type: 'string', minLength: 1, maxLength: 500 },
    color: { type: 'string', enum: ['blue', 'green', 'violet', 'orange', 'rose', 'slate'] },
    icon: { type: 'string', minLength: 1, maxLength: 8 }
  },
  required: ['id', 'label', 'x', 'y']
};
const edge = {
  type: 'object',
  additionalProperties: false,
  properties: {
    id: { type: 'string', minLength: 1, maxLength: 100 },
    source: { type: 'string', minLength: 1, maxLength: 100 },
    target: { type: 'string', minLength: 1, maxLength: 100 },
    sourceHandle: handle,
    targetHandle: handle,
    rationale: { type: 'string', minLength: 1, maxLength: 500 }
  },
  required: ['id', 'source', 'target']
};
const dailyPoint = {
  type: 'object',
  additionalProperties: false,
  properties: {
    label: { type: 'string' },
    sourceValue: { type: 'number' },
    targetValue: { type: 'number' },
    support: { type: 'string', enum: ['supportive', 'not_supportive', 'mixed'] }
  },
  required: ['label', 'sourceValue', 'targetValue', 'support']
};
const hourlyPoint = {
  type: 'object',
  additionalProperties: false,
  properties: {
    label: { type: 'string' },
    sourceValue: { type: 'number' },
    targetValue: { type: 'number' }
  },
  required: ['label', 'sourceValue', 'targetValue']
};
const relationshipEvidence = {
  type: 'object',
  additionalProperties: false,
  properties: {
    edgeId: { type: 'string' },
    summary: { type: 'string' },
    supportCount: { type: 'integer', minimum: 0, maximum: 365 },
    totalCount: { type: 'integer', minimum: 1, maximum: 365 },
    averageLag: { type: 'string' },
    strengthLabel: { type: 'string', enum: ['Exploratory', 'Weak', 'Moderate', 'Strong'] },
    consistencyLabel: { type: 'string' },
    interpretation: { type: 'string' },
    sourceUnit: { type: 'string' },
    targetUnit: { type: 'string' },
    daily: { type: 'array', maxItems: 90, items: dailyPoint },
    hourly: { type: 'array', maxItems: 48, items: hourlyPoint }
  },
  required: ['edgeId', 'summary']
};
const evidence = {
  type: 'object',
  additionalProperties: false,
  properties: {
    provider: { type: 'string', enum: ['ha_unofficial_ai', 'synthetic_example'] },
    question: { type: 'string' },
    generatedAt: { type: 'string', format: 'date-time' },
    entityIds: { type: 'array', maxItems: 100, items: { type: 'string' } },
    notes: { type: 'array', maxItems: 50, items: { type: 'string' } },
    windowLabel: { type: 'string' },
    relationships: { type: 'array', maxItems: 500, items: relationshipEvidence }
  },
  required: ['provider', 'question', 'generatedAt', 'entityIds', 'notes']
};
const day = {
  type: 'object',
  additionalProperties: false,
  properties: {
    id: { type: 'string' },
    name: { type: 'string' },
    createdAt: { type: 'string', format: 'date-time' },
    updatedAt: { type: 'string', format: 'date-time' },
    nodes: { type: 'array', maxItems: 1000, items: node },
    edges: { type: 'array', maxItems: 5000, items: edge },
    evidence
  },
  required: ['id', 'name', 'createdAt', 'updatedAt', 'nodes', 'edges']
};

export const toolDefinitions = [
  {
    name: 'launch_day_diagram_app',
    description: 'Launch the local day DAG website and return its verified localhost URL.',
    inputSchema: { type: 'object', additionalProperties: false, properties: { port: { type: 'integer', minimum: 1024, maximum: 65535, default: 3000 } } }
  },
  {
    name: 'create_day',
    description: 'Create and persist a new empty custom day.',
    inputSchema: { type: 'object', additionalProperties: false, properties: { name: { type: 'string', minLength: 1, maxLength: 100 } }, required: ['name'] }
  },
  {
    name: 'list_days',
    description: 'List all saved days without their node and edge arrays.',
    inputSchema: { type: 'object', additionalProperties: false, properties: {} }
  },
  {
    name: 'get_day',
    description: 'Load one saved day, including its boxes, directed edges, and compact evidence.',
    inputSchema: { type: 'object', additionalProperties: false, properties: { id: { type: 'string' } }, required: ['id'] }
  },
  {
    name: 'save_day',
    description: 'Validate and save the complete representation of an existing day.',
    inputSchema: { type: 'object', additionalProperties: false, properties: { day }, required: ['day'] }
  },
  {
    name: 'update_day_diagram',
    description: 'Replace only the boxes and edges of an existing day, preserving its metadata.',
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        id: { type: 'string' },
        nodes: { type: 'array', maxItems: 1000, items: node },
        edges: { type: 'array', maxItems: 5000, items: edge }
      },
      required: ['id', 'nodes', 'edges']
    }
  },
  {
    name: 'create_dag_from_ha_evidence',
    description: 'Save a DAG from compact evidence already read by an MCP host through HA Unofficial AI. This server never queries Home Assistant. Arrows are hypotheses, not proof of causation.',
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        name: { type: 'string', minLength: 1, maxLength: 100 },
        question: { type: 'string', minLength: 1, maxLength: 500 },
        nodes: {
          type: 'array',
          minItems: 1,
          maxItems: 100,
          items: {
            type: 'object',
            additionalProperties: false,
            properties: {
              id: { type: 'string' },
              label: { type: 'string' },
              entity_id: { type: 'string' },
              observed_summary: { type: 'string' },
              color: { type: 'string', enum: ['blue', 'green', 'violet', 'orange', 'rose', 'slate'] },
              icon: { type: 'string' },
              x: { type: 'number' },
              y: { type: 'number' }
            },
            required: ['id', 'label']
          }
        },
        edges: {
          type: 'array',
          maxItems: 500,
          items: {
            type: 'object',
            additionalProperties: false,
            properties: {
              id: { type: 'string' },
              source: { type: 'string' },
              target: { type: 'string' },
              source_handle: handle,
              target_handle: handle,
              rationale: { type: 'string' }
            },
            required: ['source', 'target']
          }
        },
        evidence_notes: { type: 'array', maxItems: 50, items: { type: 'string' } },
        window_label: { type: 'string' },
        relationship_evidence: { type: 'array', maxItems: 500, items: relationshipEvidence }
      },
      required: ['name', 'question', 'nodes', 'edges']
    }
  },
  {
    name: 'delete_day',
    description: 'Permanently delete one saved day.',
    inputSchema: { type: 'object', additionalProperties: false, properties: { id: { type: 'string' } }, required: ['id'] }
  }
];
