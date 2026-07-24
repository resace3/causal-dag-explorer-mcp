import { afterEach, describe, expect, it } from 'vitest';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { DayStore } from '../src/storage/dayStore.js';

const directories: string[] = [];
async function fixture() { const directory = await mkdtemp(path.join(os.tmpdir(), 'day-diagram-')); directories.push(directory); return new DayStore(path.join(directory, 'days.json')); }
afterEach(async () => { await Promise.all(directories.splice(0).map((directory) => rm(directory, { recursive: true, force: true }))); });

describe('DayStore', () => {
  it('saves and reloads labels, edges, and positions', async () => {
    const store = await fixture();
    const day = await store.create('Test Day');
    await store.save({ ...day, nodes: [
      { id: 'node-1', label: 'Wake up', x: 120, y: 200 },
      { id: 'node-2', label: 'Breakfast', x: 410, y: 230 }
    ], edges: [{ id: 'edge-1', source: 'node-1', target: 'node-2', sourceHandle: 'right', targetHandle: 'left' }] });
    const restartedStore = new DayStore(store.filePath);
    const restored = await restartedStore.get(day.id);
    expect(restored.name).toBe('Test Day');
    expect(restored.nodes).toEqual([
      { id: 'node-1', label: 'Wake up', x: 120, y: 200 },
      { id: 'node-2', label: 'Breakfast', x: 410, y: 230 }
    ]);
    expect(restored.edges).toEqual([{ id: 'edge-1', source: 'node-1', target: 'node-2', sourceHandle: 'right', targetHandle: 'left' }]);
    expect(JSON.parse(await readFile(store.filePath, 'utf8')).version).toBe(1);
  });

  it('rejects self-edges and duplicate source-target pairs', async () => {
    const store = await fixture();
    const day = await store.create('Invalid Day');
    const nodes = [{ id: 'a', label: 'A', x: 0, y: 0 }, { id: 'b', label: 'B', x: 10, y: 10 }];
    await expect(store.save({ ...day, nodes, edges: [{ id: 'self', source: 'a', target: 'a' }] })).rejects.toThrow('Self-edge');
    await expect(store.save({ ...day, nodes, edges: [{ id: 'one', source: 'a', target: 'b' }, { id: 'two', source: 'a', target: 'b' }] })).rejects.toThrow('Duplicate edge');
  });

  it('rejects a directed cycle', async () => {
    const store = await fixture();
    const day = await store.create('Cyclic Day');
    const nodes = ['a', 'b', 'c'].map((id, index) => ({ id, label: id.toUpperCase(), x: index * 100, y: index * 50 }));
    await expect(store.save({ ...day, nodes, edges: [
      { id: 'a-b', source: 'a', target: 'b' },
      { id: 'b-c', source: 'b', target: 'c' },
      { id: 'c-a', source: 'c', target: 'a' }
    ] })).rejects.toThrow('Directed cycles');
  });

  it('persists compact relationship evidence without changing the DAG', async () => {
    const store = await fixture();
    const day = await store.create('Evidence Day');
    const nodes = ['a', 'b'].map((id, index) => ({ id, label: id.toUpperCase(), x: index * 180, y: index * 60 }));
    const saved = await store.save({
      ...day,
      nodes,
      edges: [{ id: 'a-b', source: 'a', target: 'b', rationale: 'Hypothesis only.' }],
      evidence: {
        provider: 'synthetic_example',
        question: 'Does A precede B in this fixture?',
        generatedAt: new Date().toISOString(),
        entityIds: [],
        notes: ['Synthetic fixture.'],
        windowLabel: 'Two fictional days',
        relationships: [{
          edgeId: 'a-b',
          summary: 'A compact fixture.',
          daily: [
            { label: 'Day 1', sourceValue: 1, targetValue: 2, support: 'supportive' },
            { label: 'Day 2', sourceValue: 2, targetValue: 1, support: 'not_supportive' }
          ]
        }]
      }
    });
    const restored = await new DayStore(store.filePath).get(saved.id);
    expect(restored.evidence?.relationships?.[0].daily).toHaveLength(2);
    expect(restored.edges[0].rationale).toBe('Hypothesis only.');
  });

  it('rejects evidence attached to an edge that does not exist', async () => {
    const store = await fixture();
    const day = await store.create('Bad Evidence');
    await expect(store.save({
      ...day,
      evidence: {
        provider: 'synthetic_example',
        question: 'Invalid fixture',
        generatedAt: new Date().toISOString(),
        entityIds: [],
        notes: [],
        relationships: [{ edgeId: 'missing', summary: 'Invalid.' }]
      }
    })).rejects.toThrow('missing edge');
  });

  it('rejects unknown connection handles', async () => {
    const store = await fixture();
    const day = await store.create('Bad Handle Day');
    const nodes = [{ id: 'a', label: 'A', x: 0, y: 0 }, { id: 'b', label: 'B', x: 100, y: 0 }];
    await expect(store.save({ ...day, nodes, edges: [{ id: 'a-b', source: 'a', target: 'b', sourceHandle: 'diagonal' }] })).rejects.toThrow('Invalid enum value');
  });

  it('creates, lists, renames, and deletes days', async () => {
    const store = await fixture();
    const day = await store.create('Monday');
    expect((await store.list())[0].name).toBe('Monday');
    await store.save({ ...day, name: 'Tuesday' });
    expect((await store.get(day.id)).name).toBe('Tuesday');
    await store.delete(day.id);
    expect(await store.list()).toEqual([]);
  });
});
