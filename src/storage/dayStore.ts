import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import type { DayDiagram, DayEdge, DayNode, DaySummary, DiagramEvidence } from '../shared/types.js';
import { daySchema, formatValidationError } from '../shared/validation.js';

interface StoreFile { version: 1; days: DayDiagram[] }

export class DayStore {
  private queue: Promise<unknown> = Promise.resolve();

  constructor(public readonly filePath: string) {}

  private async readStore(): Promise<StoreFile> {
    try {
      const parsed: unknown = JSON.parse(await readFile(this.filePath, 'utf8'));
      if (!parsed || typeof parsed !== 'object' || !Array.isArray((parsed as StoreFile).days)) throw new Error('Invalid store structure');
      const days = (parsed as StoreFile).days.map((day) => {
        const result = daySchema.safeParse(day);
        if (!result.success) throw new Error(formatValidationError(result.error));
        return result.data;
      });
      return { version: 1, days };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return { version: 1, days: [] };
      throw new Error(`Could not read day store: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async writeStore(store: StoreFile): Promise<void> {
    await mkdir(path.dirname(this.filePath), { recursive: true });
    const temp = `${this.filePath}.${process.pid}.${Date.now()}.tmp`;
    await writeFile(temp, `${JSON.stringify(store, null, 2)}\n`, 'utf8');
    await rename(temp, this.filePath);
  }

  private locked<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.queue.then(operation, operation);
    this.queue = result.then(() => undefined, () => undefined);
    return result;
  }

  async list(): Promise<DaySummary[]> {
    const { days } = await this.readStore();
    return days.map(({ id, name, createdAt, updatedAt }) => ({ id, name, createdAt, updatedAt }))
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  }

  async get(id: string): Promise<DayDiagram> {
    const day = (await this.readStore()).days.find((item) => item.id === id);
    if (!day) throw new Error(`Day not found: ${id}`);
    return structuredClone(day);
  }

  async create(name: string, initial?: { nodes?: DayNode[]; edges?: DayEdge[]; evidence?: DiagramEvidence }): Promise<DayDiagram> {
    return this.locked(async () => {
      const store = await this.readStore();
      const now = new Date().toISOString();
      const day: DayDiagram = { id: `day-${randomUUID()}`, name: name.trim(), createdAt: now, updatedAt: now, nodes: initial?.nodes ?? [], edges: initial?.edges ?? [], ...(initial?.evidence ? { evidence: initial.evidence } : {}) };
      const result = daySchema.safeParse(day);
      if (!result.success) throw new Error(formatValidationError(result.error));
      const parsed = result.data;
      store.days.push(parsed);
      await this.writeStore(store);
      return structuredClone(parsed);
    });
  }

  async save(day: DayDiagram): Promise<DayDiagram> {
    return this.locked(async () => {
      const parsed = daySchema.safeParse({ ...day, updatedAt: new Date().toISOString() });
      if (!parsed.success) throw new Error(formatValidationError(parsed.error));
      const store = await this.readStore();
      const index = store.days.findIndex((item) => item.id === parsed.data.id);
      if (index < 0) throw new Error(`Day not found: ${parsed.data.id}`);
      const existing = store.days[index];
      const saved = { ...parsed.data, createdAt: existing.createdAt };
      store.days[index] = saved;
      await this.writeStore(store);
      return structuredClone(saved);
    });
  }

  async delete(id: string): Promise<void> {
    return this.locked(async () => {
      const store = await this.readStore();
      const remaining = store.days.filter((item) => item.id !== id);
      if (remaining.length === store.days.length) throw new Error(`Day not found: ${id}`);
      await this.writeStore({ version: 1, days: remaining });
    });
  }
}

export function defaultStorePath(): string {
  return process.env.DAY_DIAGRAM_DATA_FILE
    ? path.resolve(process.env.DAY_DIAGRAM_DATA_FILE)
    : path.resolve(process.cwd(), 'data', 'days.json');
}
