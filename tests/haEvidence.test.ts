import { afterEach, describe, expect, it } from 'vitest';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { buildHaEvidenceDiagram, haEvidenceDagInputSchema } from '../src/shared/haEvidence.js';
import { DayStore } from '../src/storage/dayStore.js';

const directories: string[] = [];

async function fixture() {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'ha-evidence-dag-'));
  directories.push(directory);
  return new DayStore(path.join(directory, 'days.json'));
}

afterEach(async () => {
  await Promise.all(directories.splice(0).map((directory) => rm(directory, { recursive: true, force: true })));
});

function fiveNodeSleepInput() {
  return haEvidenceDagInputSchema.parse({
    name: 'Sleep factors',
    question: 'What measured factors may contribute to bad sleep?',
    nodes: [
      { id: 'temperature', label: 'Warm bedroom', entity_id: 'sensor.bedroom_temperature', observed_summary: 'Higher overnight temperature was observed on several low-score nights.' },
      { id: 'humidity', label: 'High humidity', entity_id: 'sensor.bedroom_humidity', observed_summary: 'Humidity remained elevated during part of the selected period.' },
      { id: 'late-light', label: 'Late light', entity_id: 'light.bedroom', observed_summary: 'The bedroom light was on after the usual bedtime on some nights.' },
      { id: 'restlessness', label: 'Restlessness', entity_id: 'sensor.sleep_interruptions', observed_summary: 'More interruptions were recorded on some nights.' },
      { id: 'bad-sleep', label: 'Bad sleep', entity_id: 'sensor.sleep_score', observed_summary: 'This is the selected sleep outcome.' }
    ],
    edges: [
      { source: 'temperature', target: 'restlessness', source_handle: 'right', target_handle: 'left', rationale: 'A possible pathway to test; the observation alone does not establish causation.' },
      { source: 'humidity', target: 'restlessness' },
      { source: 'late-light', target: 'restlessness' },
      { source: 'late-light', target: 'bad-sleep' },
      { source: 'restlessness', target: 'bad-sleep' }
    ],
    evidence_notes: ['Illustrative summaries for an automated contract test, not live Home Assistant evidence.']
  });
}

describe('Home Assistant evidence DAGs', () => {
  it('builds and persists a five-node DAG with provenance and positions', async () => {
    const input = fiveNodeSleepInput();
    const diagram = buildHaEvidenceDiagram(input);

    expect(diagram.nodes).toHaveLength(5);
    expect(diagram.edges).toHaveLength(5);
    expect(diagram.nodes.map(({ x, y }) => [x, y])).toEqual([
      [100, 100], [350, 100], [600, 100], [100, 280], [350, 280]
    ]);
    expect(diagram.edges[0]).toMatchObject({
      id: 'edge-ha-1', source: 'temperature', target: 'restlessness', sourceHandle: 'right', targetHandle: 'left'
    });
    expect(diagram.evidence.entityIds).toHaveLength(5);

    const store = await fixture();
    const created = await store.create(input.name, diagram);
    const restored = await new DayStore(store.filePath).get(created.id);

    expect(restored.nodes[0].sourceEntityId).toBe('sensor.bedroom_temperature');
    expect(restored.nodes[0].observedSummary).toContain('low-score nights');
    expect(restored.edges[0].rationale).toContain('does not establish causation');
    expect(restored.evidence).toMatchObject({
      provider: 'ha_unofficial_ai',
      question: input.question,
      entityIds: diagram.evidence.entityIds,
      notes: input.evidence_notes
    });
  });

  it('rejects cycles before an evidence DAG is saved', async () => {
    const input = fiveNodeSleepInput();
    const diagram = buildHaEvidenceDiagram({
      ...input,
      edges: [...input.edges, { source: 'bad-sleep', target: 'late-light' }]
    });
    const store = await fixture();

    await expect(store.create(input.name, diagram)).rejects.toThrow('Directed cycles');
    expect(await store.list()).toEqual([]);
  });
});
