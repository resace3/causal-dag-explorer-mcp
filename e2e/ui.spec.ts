import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

test.describe.configure({ mode: 'serial' });

async function resetStore(request: APIRequestContext) {
  const list = await (await request.get('/api/days')).json() as Array<{ id: string }>;
  for (const item of list) await request.delete(`/api/days/${item.id}`);
  const fixture = JSON.parse(await readFile(path.resolve('data', 'example-days.json'), 'utf8')).days[0];
  const created = await (await request.post('/api/days', { data: { name: fixture.name } })).json();
  await request.put(`/api/days/${created.id}`, {
    data: {
      ...fixture,
      id: created.id,
      createdAt: created.createdAt,
      updatedAt: created.updatedAt
    }
  });
}

test.beforeEach(async ({ request }) => {
  await resetStore(request);
});

async function connect(page: Page, source: Locator, target: Locator, sourceSide = 'right', targetSide = 'left', expectNewEdge = true) {
  for (let attempt = 0; attempt < (expectNewEdge ? 2 : 1); attempt += 1) {
    const edgeCount = await page.locator('.react-flow__edge').count();
    const sourceHandle = source.locator(`.react-flow__handle-${sourceSide}`);
    const targetHandle = target.locator(`.react-flow__handle-${targetSide}`);
    const start = await sourceHandle.boundingBox();
    const end = await targetHandle.boundingBox();
    if (!start || !end) throw new Error('A connection handle was not visible');
    await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
    await page.mouse.down();
    await page.waitForTimeout(60);
    await page.mouse.move((start.x + end.x) / 2, (start.y + end.y) / 2, { steps: 12 });
    await page.mouse.move(end.x + end.width / 2, end.y + end.height / 2, { steps: 12 });
    await page.waitForTimeout(60);
    await page.mouse.up();
    await page.waitForTimeout(100);
    if (!expectNewEdge || await page.locator('.react-flow__edge').count() === edgeCount + 1) return;
  }
  throw new Error('The directed edge was not created after two natural pointer drags');
}

async function renameBox(page: Page, current: string, next: string) {
  await page.getByRole('button', { name: `Rename ${current}`, exact: true }).click();
  const editor = page.getByLabel('Name', { exact: true });
  await editor.fill(next);
  await page.getByRole('button', { name: 'Rename', exact: true }).click();
}

async function clickEdgePath(page: Page, edge: Locator) {
  const point = await edge.locator('.react-flow__edge-path').evaluate((element) => {
    const path = element as SVGPathElement;
    const matrix = path.getScreenCTM();
    if (!matrix) return null;
    const length = path.getTotalLength();
    for (const ratio of [.15, .25, .35, .5, .65, .75, .85]) {
      const local = path.getPointAtLength(length * ratio);
      const screen = new DOMPoint(local.x, local.y).matrixTransform(matrix);
      const hit = document.elementFromPoint(screen.x, screen.y);
      if (hit?.closest('.react-flow__edge') === path.closest('.react-flow__edge')) return { x: screen.x, y: screen.y };
    }
    return null;
  });
  if (!point) throw new Error('No visible segment of the requested edge could be clicked');
  await page.mouse.click(point.x, point.y);
}

test('synthetic explorer renders every evidence and navigation view', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Causal DAG Explorer ✦' })).toBeVisible();
  await expect(page.locator('.react-flow__node')).toHaveCount(5);
  await expect(page.locator('.react-flow__edge')).toHaveCount(5);
  await expect(page.locator('.node-logo')).toHaveCount(5);
  for (const kind of ['activity', 'sleep', 'stress', 'mood', 'productivity']) {
    await expect(page.locator(`.node-logo[data-icon-kind="${kind}"]`)).toHaveCount(1);
  }
  expect(await page.locator('.react-flow__edge-path').evaluateAll((paths) =>
    paths.every((path) => path.getAttribute('d')?.includes('C'))
  )).toBe(true);
  await expect(page.getByRole('heading', { name: 'Sleep → Mood' })).toBeVisible();
  await expect(page.getByRole('listitem')).toHaveCount(30);
  await expect(page.getByText('20 of 30 supportive', { exact: true })).toBeVisible();

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export JSON', exact: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('wellbeing-example.json');
  const downloadPath = await download.path();
  expect(downloadPath).toBeTruthy();
  const exported = JSON.parse(await readFile(downloadPath!, 'utf8'));
  expect(exported.name).toBe('Wellbeing example');
  expect(exported.nodes).toHaveLength(5);
  expect(exported.edges).toHaveLength(5);

  await page.getByRole('tab', { name: 'Timelines', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Aligned evidence timeline' })).toBeVisible();
  await page.getByRole('tab', { name: 'Descriptive stats', exact: true }).click();
  await expect(page.getByText('No p-values or model fit', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  await expect(page.getByText('5 boxes, 5 edges', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Data', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Diagram data' })).toBeVisible();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(page.getByText('DAG safeguards', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'DAG View', exact: true }).click();
  await expect(page.getByRole('region', { name: 'DAG diagram card' })).toBeVisible();
});

test('keeps collapsed sidebar navigation named and functional', async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 900 });
  await page.goto('/');

  for (const label of ['DAG View', 'Timelines', 'Evidence', 'Data', 'Settings']) {
    await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible();
  }

  await page.getByRole('button', { name: 'Timelines', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Aligned evidence timeline' })).toBeVisible();
  await page.getByRole('button', { name: 'Evidence', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Evidence strip' })).toBeVisible();
  await page.getByRole('button', { name: 'DAG View', exact: true }).click();
  await expect(page.getByRole('region', { name: 'DAG diagram card' })).toBeVisible();
});

test('creates, edits, connects, rejects invalid edges, saves, and reloads a five-node DAG', async ({ page, request }) => {
  await page.goto('/');
  await page.locator('.new-day').click();
  await page.getByLabel('Name', { exact: true }).fill('Five-node UI test');
  await page.getByRole('button', { name: 'Create Day', exact: true }).click();

  for (let index = 0; index < 5; index += 1) await page.getByTestId('add-box').click();
  for (const [index, label] of ['Exercise', 'Sleep', 'Stress', 'Mood', 'Productivity'].entries()) {
    await renameBox(page, `Box ${index + 1}`, label);
  }
  await expect(page.locator('.react-flow__node')).toHaveCount(5);
  for (const kind of ['activity', 'sleep', 'stress', 'mood', 'productivity']) {
    await expect(page.locator(`.node-logo[data-icon-kind="${kind}"]`)).toHaveCount(1);
  }

  const node = (label: string) => page.locator('.day-node').filter({ hasText: label });
  const exercise = node('Exercise');
  const sleep = node('Sleep');
  const stress = node('Stress');
  const mood = node('Mood');
  const productivity = node('Productivity');

  const moveTarget = await exercise.boundingBox();
  if (!moveTarget) throw new Error('Exercise node was not visible');
  await page.mouse.move(moveTarget.x + 70, moveTarget.y + 24);
  await page.mouse.down();
  await page.mouse.move(moveTarget.x + 150, moveTarget.y + 80, { steps: 12 });
  await page.mouse.up();

  await connect(page, exercise, sleep, 'bottom', 'top');
  await connect(page, exercise, mood, 'right', 'top');
  await connect(page, sleep, mood);
  await connect(page, stress, mood);
  await connect(page, mood, productivity);
  await expect(page.locator('.react-flow__edge')).toHaveCount(5);
  expect(await page.locator('.react-flow__edge-path').evaluateAll((paths) =>
    paths.every((path) => path.getAttribute('d')?.includes('C'))
  )).toBe(true);

  await connect(page, sleep, sleep, 'right', 'left', false);
  await expect(page.getByRole('alert')).toContainText('cannot connect to itself');
  await connect(page, sleep, mood, 'right', 'left', false);
  await expect(page.getByRole('alert')).toContainText('already exists');
  await connect(page, mood, sleep, 'right', 'left', false);
  await expect(page.getByRole('alert')).toContainText('directed cycle');
  await expect(page.locator('.react-flow__edge')).toHaveCount(5);

  const edge = page.locator('.react-flow__edge');
  expect(await edge.count()).toBe(5);
  const moodId = await mood.evaluate((element) => element.parentElement?.getAttribute('data-id'));
  const productivityId = await productivity.evaluate((element) => element.parentElement?.getAttribute('data-id'));
  const moodProductivity = page.locator(`[aria-label="Edge from ${moodId} to ${productivityId}"]`);
  await clickEdgePath(page, moodProductivity);
  await expect(page.getByText('Edge selected', { exact: true })).toBeVisible();
  await page.keyboard.press('Delete');
  await expect(page.locator('.react-flow__edge')).toHaveCount(4);
  await connect(page, mood, productivity);
  await expect(page.locator('.react-flow__edge')).toHaveCount(5);

  await expect(page.getByTestId('unsaved-indicator')).toBeVisible();
  await page.getByTestId('save-day').click();
  await expect(page.getByTestId('unsaved-indicator')).toHaveCount(0);

  const daysResponse = await request.get('/api/days');
  const days = await daysResponse.json() as Array<{ id: string; name: string }>;
  const savedSummary = days.find((item) => item.name === 'Five-node UI test');
  expect(savedSummary).toBeTruthy();
  const saved = await (await request.get(`/api/days/${savedSummary!.id}`)).json();
  expect(saved.nodes).toHaveLength(5);
  expect(saved.edges).toHaveLength(5);
  expect(saved.nodes.find((item: { label: string }) => item.label === 'Exercise').x).toBeGreaterThan(100);

  await page.reload();
  await expect(page.getByRole('heading', { name: 'Five-node UI test' })).toBeVisible();
  await expect(page.locator('.react-flow__node')).toHaveCount(5);
  await expect(page.locator('.react-flow__edge')).toHaveCount(5);
  for (const label of ['Exercise', 'Sleep', 'Stress', 'Mood', 'Productivity']) {
    await expect(page.getByText(label, { exact: true })).toBeVisible();
  }
});

test('handles day rename, clear confirmation, dirty switching, and deletion', async ({ page }) => {
  const example = JSON.parse(await readFile(path.resolve('data', 'example-days.json'), 'utf8')).days[0];
  const createdResponse = await page.request.post('/api/days', { data: { name: 'Five-node UI test' } });
  const created = await createdResponse.json();
  await page.request.put(`/api/days/${created.id}`, {
    data: { ...example, id: created.id, name: 'Five-node UI test', createdAt: created.createdAt, updatedAt: created.updatedAt }
  });
  await page.goto('/');
  const renameDay = page.getByRole('button', { name: 'Rename Five-node UI test', exact: true });
  await renameDay.click();
  await page.getByLabel('Name', { exact: true }).fill('Five-node UI test renamed');
  await page.getByRole('button', { name: 'Rename', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Five-node UI test renamed' })).toBeVisible();

  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: 'Clear Canvas', exact: true }).click();
  await expect(page.locator('.react-flow__node')).toHaveCount(5);
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Clear Canvas', exact: true }).click();
  await expect(page.locator('.react-flow__node')).toHaveCount(0);
  await expect(page.getByTestId('unsaved-indicator')).toBeVisible();

  page.once('dialog', (dialog) => dialog.dismiss());
  await page.locator('.day-open').filter({ hasText: 'Wellbeing example' }).click();
  await expect(page.getByRole('heading', { name: 'Five-node UI test renamed' })).toBeVisible();
  page.once('dialog', (dialog) => dialog.accept());
  await page.locator('.day-open').filter({ hasText: 'Wellbeing example' }).click();
  await expect(page.getByRole('heading', { name: 'Wellbeing example' })).toBeVisible();

  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Delete Five-node UI test renamed', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Delete Five-node UI test renamed', exact: true })).toHaveCount(0);
});
