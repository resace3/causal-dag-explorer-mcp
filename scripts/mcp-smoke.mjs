import assert from 'node:assert/strict';
import { rm, mkdir } from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import process from 'node:process';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => server.once('error', reject).listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Could not allocate a test port');
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return address.port;
}

const directory = path.resolve('.tmp');
const dataFile = path.join(directory, 'mcp-smoke-days.json');
await mkdir(directory, { recursive: true });
await rm(dataFile, { force: true });
const environment = Object.fromEntries(Object.entries(process.env).filter((entry) => typeof entry[1] === 'string'));
environment.DAY_DIAGRAM_DATA_FILE = dataFile;

const transport = new StdioClientTransport({
  command: process.execPath,
  args: [path.resolve('dist/node/mcp/index.js')],
  cwd: process.cwd(),
  env: environment,
  stderr: 'pipe'
});
const client = new Client({ name: 'causal-dag-explorer-smoke', version: '1.0.0' }, { capabilities: {} });
let launchedPid;

async function call(name, args = {}) {
  const result = await client.callTool({ name, arguments: args });
  assert.equal(result.isError, false, `${name} returned an MCP error`);
  const block = result.content[0];
  assert.equal(block.type, 'text');
  return JSON.parse(block.text);
}

try {
  await client.connect(transport);
  const tools = await client.listTools();
  assert.deepEqual(tools.tools.map((tool) => tool.name), [
    'launch_day_diagram_app',
    'create_day',
    'list_days',
    'get_day',
    'save_day',
    'update_day_diagram',
    'create_dag_from_ha_evidence',
    'delete_day'
  ]);

  const port = await freePort();
  const launched = await call('launch_day_diagram_app', { port });
  launchedPid = launched.pid;
  assert.equal((await fetch(launched.url)).status, 200);

  const created = await call('create_day', { name: 'MCP smoke day' });
  const nodes = [
    { id: 'exercise', label: 'Exercise', x: 80, y: 80 },
    { id: 'sleep', label: 'Sleep', x: 320, y: 80 },
    { id: 'stress', label: 'Stress', x: 80, y: 260 },
    { id: 'mood', label: 'Mood', x: 560, y: 160 },
    { id: 'productivity', label: 'Productivity', x: 800, y: 160 }
  ];
  const edges = [
    { id: 'exercise-sleep', source: 'exercise', target: 'sleep' },
    { id: 'exercise-mood', source: 'exercise', target: 'mood' },
    { id: 'sleep-mood', source: 'sleep', target: 'mood' },
    { id: 'stress-mood', source: 'stress', target: 'mood' },
    { id: 'mood-productivity', source: 'mood', target: 'productivity' }
  ];
  await call('update_day_diagram', { id: created.id, nodes, edges });
  const restored = await call('get_day', { id: created.id });
  assert.equal(restored.nodes.length, 5);
  assert.equal(restored.edges.length, 5);
  await call('save_day', { day: { ...restored, name: 'MCP smoke day renamed' } });

  const imported = await call('create_dag_from_ha_evidence', {
    name: 'Synthetic HA contract',
    question: 'Which fictional inputs precede the outcome?',
    nodes: [
      { id: 'temperature', label: 'Temperature', entity_id: 'sensor.synthetic_temperature' },
      { id: 'outcome', label: 'Outcome', entity_id: 'sensor.synthetic_outcome' }
    ],
    edges: [{ source: 'temperature', target: 'outcome', rationale: 'Synthetic contract test; not a causal claim.' }],
    evidence_notes: ['Synthetic MCP smoke test.']
  });
  assert.equal(imported.evidence.provider, 'ha_unofficial_ai');
  assert.equal((await call('list_days')).length, 2);
  await call('delete_day', { id: imported.id });
  await call('delete_day', { id: created.id });
  assert.deepEqual(await call('list_days'), []);
  console.log('MCP smoke test passed: launch plus all seven data tools.');
} finally {
  if (launchedPid) {
    try { process.kill(launchedPid); } catch {}
  }
  await client.close().catch(() => undefined);
  await rm(dataFile, { force: true });
}
