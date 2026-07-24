import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { z } from 'zod';
import type { DayDiagram } from '../shared/types.js';
import { createDaySchema, daySchema, formatValidationError, updateDiagramSchema } from '../shared/validation.js';
import { buildHaEvidenceDiagram, haEvidenceDagInputSchema } from '../shared/haEvidence.js';
import { DayStore, defaultStorePath } from '../storage/dayStore.js';
import { launch } from './launcher.js';
import { toolDefinitions } from './tools.js';

const server = new Server({ name: 'day-diagram-mcp', version: '1.1.0' }, { capabilities: { tools: {} } });
const store = new DayStore(defaultStorePath());
const idSchema = z.string().trim().min(1).max(100);
const response = (value: unknown, isError = false) => ({ isError, content: [{ type: 'text' as const, text: JSON.stringify(value, null, 2) }] });

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: [...toolDefinitions] }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  try {
    const args = request.params.arguments ?? {};
    switch (request.params.name) {
      case 'launch_day_diagram_app': return response(await launch(z.number().int().min(1024).max(65535).default(3000).parse(args.port)));
      case 'create_day': return response(await store.create(createDaySchema.parse(args).name));
      case 'list_days': return response(await store.list());
      case 'get_day': return response(await store.get(idSchema.parse(args.id)));
      case 'save_day': {
        const parsed = daySchema.safeParse(args.day);
        if (!parsed.success) throw new Error(formatValidationError(parsed.error));
        return response(await store.save(parsed.data));
      }
      case 'update_day_diagram': {
        const id = idSchema.parse(args.id);
        const diagram = updateDiagramSchema.parse({ nodes: args.nodes, edges: args.edges });
        const existing: DayDiagram = await store.get(id);
        return response(await store.save({ ...existing, ...diagram }));
      }
      case 'create_dag_from_ha_evidence': {
        const parsed = haEvidenceDagInputSchema.parse(args);
        const diagram = buildHaEvidenceDiagram(parsed);
        return response(await store.create(parsed.name, diagram));
      }
      case 'delete_day': await store.delete(idSchema.parse(args.id)); return response({ success: true });
      default: throw new Error(`Unknown tool: ${request.params.name}`);
    }
  } catch (error) {
    return response({ success: false, error: error instanceof Error ? error.message : String(error) }, true);
  }
});

await server.connect(new StdioServerTransport());
