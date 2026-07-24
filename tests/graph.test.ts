import { describe, expect, it } from 'vitest';
import { connectionProblem, hasDirectedCycle, hasPath } from '../src/shared/graph.js';

const dagEdges = [
  { source: 'a', target: 'b' },
  { source: 'a', target: 'c' },
  { source: 'b', target: 'd' },
  { source: 'c', target: 'd' },
  { source: 'd', target: 'e' }
];

describe('directed graph rules', () => {
  it('accepts a five-node DAG with branching and merging', () => {
    expect(hasDirectedCycle(['a', 'b', 'c', 'd', 'e'], dagEdges)).toBe(false);
    expect(hasPath(dagEdges, 'a', 'e')).toBe(true);
    expect(connectionProblem(dagEdges, 'b', 'e')).toBeNull();
  });

  it('rejects self edges, duplicates, and edges that close a cycle', () => {
    expect(connectionProblem(dagEdges, 'a', 'a')).toContain('itself');
    expect(connectionProblem(dagEdges, 'a', 'b')).toContain('already exists');
    expect(connectionProblem(dagEdges, 'e', 'a')).toContain('cycle');
    expect(hasDirectedCycle(['a', 'b', 'c', 'd', 'e'], [...dagEdges, { source: 'e', target: 'a' }])).toBe(true);
  });
});
