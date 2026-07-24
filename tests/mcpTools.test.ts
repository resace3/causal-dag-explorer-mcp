import { describe, expect, it } from 'vitest';
import { toolDefinitions } from '../src/mcp/tools.js';

describe('MCP tool contracts', () => {
  it('publishes the complete day-diagram tool set with object schemas', () => {
    expect(toolDefinitions.map((tool) => tool.name)).toEqual([
      'launch_day_diagram_app',
      'create_day',
      'list_days',
      'get_day',
      'save_day',
      'update_day_diagram',
      'create_dag_from_ha_evidence',
      'delete_day'
    ]);
    for (const tool of toolDefinitions) {
      expect(tool.inputSchema.type).toBe('object');
      expect(tool.description.length).toBeGreaterThan(20);
    }
  });

  it('describes actual node, edge, and relationship evidence fields', () => {
    const update = toolDefinitions.find((tool) => tool.name === 'update_day_diagram');
    const fromHa = toolDefinitions.find((tool) => tool.name === 'create_dag_from_ha_evidence');
    expect(update?.inputSchema.properties.nodes.items.required).toEqual(['id', 'label', 'x', 'y']);
    expect(update?.inputSchema.properties.edges.items.required).toEqual(['id', 'source', 'target']);
    expect(fromHa?.inputSchema.properties.relationship_evidence.items.required).toEqual(['edgeId', 'summary']);
    expect(fromHa?.description).toContain('never queries Home Assistant');
  });
});
