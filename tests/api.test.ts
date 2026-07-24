import { afterEach, describe, expect, it } from 'vitest';
import { mkdtemp, rm } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import type { Server } from 'node:http';
import { createApp } from '../src/server/app.js';
import { DayStore } from '../src/storage/dayStore.js';

const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => { await Promise.all(cleanups.splice(0).map((cleanup) => cleanup())); });

describe('day API', () => {
  it('supports the complete persistence workflow', async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), 'day-api-'));
    const server: Server = createApp(new DayStore(path.join(directory, 'days.json'))).listen(0, '127.0.0.1');
    cleanups.push(async () => { await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve())); await rm(directory, { recursive: true, force: true }); });
    await new Promise<void>((resolve) => server.once('listening', resolve));
    const address = server.address(); if (!address || typeof address === 'string') throw new Error('No test port');
    const base = `http://127.0.0.1:${address.port}`;
    const created = await (await fetch(`${base}/api/days`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: 'Workflow' }) })).json();
    const payload = { ...created, nodes: [{ id: 'one', label: 'One', x: 25, y: 40 }, { id: 'two', label: 'Two', x: 300, y: 180 }], edges: [{ id: 'one-two', source: 'one', target: 'two' }] };
    expect((await fetch(`${base}/api/days/${created.id}`, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) })).status).toBe(200);
    const loaded = await (await fetch(`${base}/api/days/${created.id}`)).json();
    expect(loaded.nodes[1]).toMatchObject({ label: 'Two', x: 300, y: 180 });
    expect(loaded.edges).toHaveLength(1);
  });
});
