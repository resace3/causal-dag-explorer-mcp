import { describe, expect, it } from 'vitest';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { daySchema } from '../src/shared/validation.js';

describe('public example data', () => {
  it('is synthetic, valid, and exercises a five-node evidence DAG', async () => {
    const store = JSON.parse(await readFile(path.resolve('data', 'example-days.json'), 'utf8'));
    expect(store.version).toBe(1);
    expect(store.days).toHaveLength(1);
    const parsed = daySchema.parse(store.days[0]);
    expect(parsed.nodes).toHaveLength(5);
    expect(parsed.edges).toHaveLength(5);
    expect(parsed.evidence?.provider).toBe('synthetic_example');
    expect(parsed.evidence?.entityIds).toEqual([]);
    expect(parsed.evidence?.relationships?.[0].daily).toHaveLength(30);
    expect(JSON.stringify(parsed).toLowerCase()).not.toContain(['nick', '_r'].join(''));
  });
});
