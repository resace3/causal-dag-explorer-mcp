export interface DirectedEdge {
  source: string;
  target: string;
}

export function hasPath(edges: DirectedEdge[], start: string, goal: string): boolean {
  if (start === goal) return true;
  const outgoing = new Map<string, string[]>();
  for (const edge of edges) outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge.target]);
  const pending = [start];
  const visited = new Set<string>();
  while (pending.length) {
    const current = pending.pop()!;
    if (current === goal) return true;
    if (visited.has(current)) continue;
    visited.add(current);
    pending.push(...(outgoing.get(current) ?? []));
  }
  return false;
}

export function connectionProblem(edges: DirectedEdge[], source?: string | null, target?: string | null): string | null {
  if (!source || !target) return 'Connect one box handle to another box handle.';
  if (source === target) return 'A box cannot connect to itself.';
  if (edges.some((edge) => edge.source === source && edge.target === target)) return 'That directed edge already exists.';
  if (hasPath(edges, target, source)) return 'That edge would create a directed cycle.';
  return null;
}

export function hasDirectedCycle(nodeIds: Iterable<string>, edges: DirectedEdge[]): boolean {
  const degree = new Map<string, number>();
  const outgoing = new Map<string, string[]>();
  for (const id of nodeIds) { degree.set(id, 0); outgoing.set(id, []); }
  for (const edge of edges) {
    if (!degree.has(edge.source) || !degree.has(edge.target)) continue;
    outgoing.get(edge.source)!.push(edge.target);
    degree.set(edge.target, degree.get(edge.target)! + 1);
  }
  const queue = [...degree].filter(([, value]) => value === 0).map(([id]) => id);
  let visited = 0;
  while (queue.length) {
    const id = queue.shift()!;
    visited += 1;
    for (const target of outgoing.get(id) ?? []) {
      const next = degree.get(target)! - 1;
      degree.set(target, next);
      if (next === 0) queue.push(target);
    }
  }
  return visited !== degree.size;
}
