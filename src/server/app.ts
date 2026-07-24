import express, { type ErrorRequestHandler } from 'express';
import cors from 'cors';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';
import type { DayDiagram } from '../shared/types.js';
import { createDaySchema, daySchema, formatValidationError } from '../shared/validation.js';
import { DayStore } from '../storage/dayStore.js';

const idSchema = z.string().trim().min(1).max(100);

export function createApp(store: DayStore) {
  const app = express();
  app.use(cors({ origin: process.env.DAY_DIAGRAM_WEB_ORIGIN ?? false }));
  app.use(express.json({ limit: '2mb' }));
  app.get('/health', (_req, res) => res.json({ status: 'ok', service: 'day-diagram-app' }));
  app.get('/api/days', async (_req, res, next) => { try { res.json(await store.list()); } catch (error) { next(error); } });
  app.post('/api/days', async (req, res, next) => { try { res.status(201).json(await store.create(createDaySchema.parse(req.body).name)); } catch (error) { next(error); } });
  app.get('/api/days/:id', async (req, res, next) => { try { res.json(await store.get(idSchema.parse(req.params.id))); } catch (error) { next(error); } });
  app.put('/api/days/:id', async (req, res, next) => {
    try {
      const id = idSchema.parse(req.params.id);
      const candidate = daySchema.safeParse({ ...(req.body as DayDiagram), id });
      if (!candidate.success) throw new Error(formatValidationError(candidate.error));
      res.json(await store.save(candidate.data));
    } catch (error) { next(error); }
  });
  app.delete('/api/days/:id', async (req, res, next) => { try { await store.delete(idSchema.parse(req.params.id)); res.status(204).end(); } catch (error) { next(error); } });

  const here = path.dirname(fileURLToPath(import.meta.url));
  const webRoot = path.resolve(here, '../../web');
  app.use('/docs', express.static(path.resolve(process.cwd(), 'docs')));
  app.use(express.static(webRoot));
  app.get('*all', (_req, res, next) => res.sendFile(path.join(webRoot, 'index.html'), (error) => error ? next(error) : undefined));

  const errors: ErrorRequestHandler = (error, _req, res, _next) => {
    const message = error instanceof z.ZodError ? formatValidationError(error) : error instanceof Error ? error.message : 'Unexpected error';
    const status = message.startsWith('Day not found:') ? 404 : 400;
    console.error(`[day-diagram] ${message}`);
    res.status(status).json({ error: message });
  };
  app.use(errors);
  return app;
}
