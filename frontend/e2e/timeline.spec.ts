import { expect, test, type Page } from '@playwright/test';

/**
 * End-to-end run against the local backend (mock or live data).
 *
 * The assertions are written to hold for either, because the whole point of the
 * app is that it reports honestly whatever the configured sources returned.
 */

async function waitForTimeline(page: Page) {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Yesterday', level: 1 })).toBeVisible();
  await expect(page.getByTestId('status-card')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('timeline-expanded')).toBeVisible({ timeout: 30_000 });
}

test.describe('Yesterday timeline', () => {
  test('renders the page shell with Yesterday as the only navigation item', async ({ page }) => {
    await waitForTimeline(page);

    const nav = page.getByRole('navigation', { name: 'Main navigation' });
    await expect(nav.getByRole('button')).toHaveCount(1);
    await expect(page.getByTestId('nav-yesterday')).toHaveAttribute('aria-current', 'page');

    for (const forbidden of ['Home', 'Trends', 'Insights', 'Settings', 'Reports']) {
      await expect(nav.getByText(forbidden, { exact: true })).toHaveCount(0);
    }

    await expect(page.getByText('Your data from yesterday, 12:00 AM to 11:59 PM')).toBeVisible();
    await expect(page.getByText('All times shown in your local time')).toBeVisible();
  });

  test('picks another day from the calendar', async ({ page }) => {
    await waitForTimeline(page);

    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading).toHaveText('Yesterday');

    // Step back a few days from whatever "yesterday" is.
    const yesterday = await page.evaluate(async () => {
      const response = await fetch('/api/days');
      return (await response.json()).yesterday as string;
    });
    const target = new Date(`${yesterday}T12:00:00Z`);
    target.setUTCDate(target.getUTCDate() - 3);
    const iso = target.toISOString().slice(0, 10);

    await page.getByTestId(`calendar-day-${iso}`).click();
    await expect(heading).not.toHaveText('Yesterday', { timeout: 60_000 });
    await expect(page.getByTestId('timeline-expanded').or(page.getByText(/No data source/))).toBeVisible({
      timeout: 60_000,
    });

    // The Yesterday item goes back.
    await page.getByTestId('nav-yesterday').click();
    await expect(heading).toHaveText('Yesterday', { timeout: 60_000 });
  });

  test('builds an expected DAG for an outcome and exposure', async ({ page }) => {
    await waitForTimeline(page);

    await page.getByTestId('mode-dag').click();
    const dag = page.getByTestId('timeline-dag');
    await expect(dag).toBeVisible();

    // Outcome alone is enough to get a graph.
    await expect(dag.locator('[data-testid^="dag-node-"]').first()).toBeVisible({
      timeout: 30_000,
    });

    // Naming an exposure adds the roles that only exist relative to one.
    await page.getByTestId('dag-exposure').selectOption('exercise');
    await expect(dag.getByTestId('dag-row-sleep_duration')).toBeVisible({ timeout: 30_000 });
    await expect(dag.getByTestId('dag-row-exercise')).toContainText('Exposure');
    await expect(dag.getByTestId('dag-row-sleep_duration')).toContainText('Outcome');

    // A node opens its own explanation.
    await dag.locator('[data-testid^="dag-node-"]').first().click();
    await expect(dag.getByTestId('dag-node-detail')).toBeVisible();

    // Switching back leaves the timeline intact.
    await page.getByTestId('mode-expanded').click();
    await expect(page.getByTestId('timeline-expanded')).toBeVisible();
  });

  test('places DAG nodes on the same clock as the timeline', async ({ page }) => {
    await waitForTimeline(page);
    await page.getByTestId('mode-dag').click();
    const dag = page.getByTestId('timeline-dag');
    await expect(dag.locator('[data-testid^="dag-node-"]').first()).toBeVisible({
      timeout: 30_000,
    });

    // The axis is the day's, shared with the expanded view.
    for (const label of ['12 AM', '6 AM', '12 PM', '6 PM']) {
      await expect(dag.getByText(label, { exact: true }).first()).toBeVisible();
    }

    // Every drawn arrow must run forwards in time: the effect's node is never
    // left of the cause's node.
    const backwards = await page.evaluate(async () => {
      const response = await fetch('/api/dag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outcome: 'sleep_duration', exposure: 'exercise' }),
      });
      const body = await response.json();
      const at = new Map(
        body.timeline.occurrences.map((o: { id: string; start: string }) => [
          o.id,
          Date.parse(o.start),
        ]),
      );
      return body.timeline.links.filter(
        (link: { source: string; target: string }) =>
          (at.get(link.target) ?? 0) < (at.get(link.source) ?? 0),
      ).length;
    });
    expect(backwards).toBe(0);
  });

  test('adds a row from a description, and refuses one it cannot read', async ({ page }) => {
    await waitForTimeline(page);

    // Start clean, so the run is repeatable.
    await page.evaluate(async () => {
      const body = await (await fetch('/api/rows')).json();
      await Promise.all(
        body.rows.map((row: { id: string }) =>
          fetch(`/api/rows/${row.id}`, { method: 'DELETE' }),
        ),
      );
    });
    await page.reload();
    await expect(page.getByTestId('timeline-expanded')).toBeVisible({ timeout: 30_000 });

    await page.getByTestId('add-row-open').scrollIntoViewIfNeeded();
    await page.getByTestId('add-row-open').click();
    const reading = page.getByTestId('add-row-reading');

    // A request naming no real stream is refused, and Add stays unavailable —
    // nothing is created on a reading the user has not seen and agreed with.
    await page.getByTestId('add-row-prompt').fill('blood glucose above 7');
    await expect(reading).toContainText(/No stream in this day matches/, { timeout: 15_000 });
    await expect(page.getByTestId('add-row-submit')).toBeDisabled();

    // A readable one shows what it understood before anything happens.
    await page.getByTestId('add-row-prompt').fill('heart rate below 50');
    await expect(reading).toContainText(/Understood as/, { timeout: 15_000 });
    await expect(reading).toContainText(/below 50/);
    await expect(page.getByTestId('add-row-submit')).toBeEnabled();

    await page.getByTestId('add-row-submit').click();

    // The row lands on the timeline, and is deletable rather than merely hidden.
    const row = page.locator('[data-testid^="lane-label-custom_"]').first();
    await expect(row).toBeVisible({ timeout: 60_000 });
    await expect(row).toContainText(/below 50/);
    await expect(
      page.locator('[data-testid^="lane-delete-custom_"]').first(),
    ).toHaveCount(1);

    await page.evaluate(async () => {
      const body = await (await fetch('/api/rows')).json();
      await Promise.all(
        body.rows.map((r: { id: string }) => fetch(`/api/rows/${r.id}`, { method: 'DELETE' })),
      );
    });
  });

  test('draws a causal arrow by dragging between rows', async ({ page }) => {
    // Editing lists every variable, so both ends of the drag need to fit.
    await page.setViewportSize({ width: 1400, height: 1200 });
    await waitForTimeline(page);
    await page.getByTestId('mode-dag').click();
    const dag = page.getByTestId('timeline-dag');
    await expect(dag).toBeVisible();
    await page.getByTestId('dag-edit-toggle').click();

    // Editing gives every variable a row, including ones with no data today —
    // otherwise the arrows most worth adding could never be drawn.
    const anchor = page.getByTestId('dag-anchor-stress');
    await expect(anchor).toBeVisible({ timeout: 30_000 });

    const handle = page.getByTestId('dag-handle-stress');
    await handle.scrollIntoViewIfNeeded();
    const from = await handle.boundingBox();
    expect(from).not.toBeNull();

    await page.mouse.move(from!.x + from!.width / 2, from!.y + from!.height / 2);
    await page.mouse.down();
    await page.mouse.move(from!.x + 150, from!.y + 40, { steps: 10 });

    // Whole rows are the drop target, and only exist mid-drag.
    const drop = page.getByTestId('dag-drop-device_use');
    const to = await drop.boundingBox();
    expect(to).not.toBeNull();
    await page.mouse.move(to!.x + to!.width / 2, to!.y + to!.height / 2, { steps: 10 });
    await page.mouse.up();

    // The arrow is now in the model, and labelled as the user's.
    await expect
      .poll(
        async () =>
          page.evaluate(async () => {
            const response = await fetch('/api/dag/edges');
            const body = await response.json();
            return body.edges.filter(
              (edge: { source: string; target: string; origin: string }) =>
                edge.source === 'stress' && edge.target === 'device_use',
            ).length;
          }),
        { timeout: 20_000 },
      )
      .toBe(1);

    // Clean up so the run is repeatable.
    await page.evaluate(() =>
      fetch('/api/dag/edges/stress/device_use', { method: 'DELETE' }),
    );
  });

  test('refuses a dragged arrow that would create a cycle, and says why', async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 1200 });
    await waitForTimeline(page);
    await page.getByTestId('mode-dag').click();
    await page.getByTestId('dag-edit-toggle').click();
    await expect(page.getByTestId('dag-anchor-stress')).toBeVisible({ timeout: 30_000 });

    // sleep_onset -> sleep_duration is in the model, so the reverse closes a
    // loop. Both are on screen for this outcome.
    const handle = page.getByTestId('dag-handle-sleep_duration').first();
    await handle.scrollIntoViewIfNeeded();
    const from = await handle.boundingBox();
    await page.mouse.move(from!.x + from!.width / 2, from!.y + from!.height / 2);
    await page.mouse.down();
    await page.mouse.move(from!.x + 120, from!.y + 30, { steps: 8 });
    const to = await page.getByTestId('dag-drop-sleep_onset').boundingBox();
    await page.mouse.move(to!.x + to!.width / 2, to!.y + to!.height / 2, { steps: 8 });
    await page.mouse.up();

    const error = page.getByTestId('dag-edit-error');
    await expect(error).toBeVisible({ timeout: 20_000 });
    await expect(error).toContainText(/cycle/i);
  });

  test('keeps the DAG to the graph itself, with no prose below it', async ({ page }) => {
    await waitForTimeline(page);
    await page.getByTestId('mode-dag').click();
    const dag = page.getByTestId('timeline-dag');
    await page.getByTestId('dag-exposure').selectOption('exercise');
    await expect(dag.getByTestId('dag-row-sleep_duration')).toBeVisible({ timeout: 30_000 });

    for (const removed of [
      /not on this day.s clock/i,
      /could not be drawn/i,
      /What this implies for an analysis/i,
      /Hypothesised structure/i,
      /assumptions, not findings/i,
    ]) {
      await expect(dag.getByText(removed)).toHaveCount(0);
    }

    // The graph and its legend are what remain.
    await expect(dag.getByText(/Immediate — within 2 hours/)).toBeVisible();
  });

  test('no longer shows the observed-timing narrative', async ({ page }) => {
    await waitForTimeline(page);
    await expect(page.getByText('Observed timing')).toHaveCount(0);
    await expect(page.getByText(/These are descriptions of when things happened/)).toHaveCount(0);
  });

  test('lists every data source as an MCP integration', async ({ page }) => {
    await waitForTimeline(page);

    const panel = page.getByRole('region', { name: 'MCPs' });
    await expect(panel).toBeVisible();
    await expect(panel.locator('h2')).toHaveText('MCPs');
    await expect(page.getByTestId('source-home_assistant')).toContainText(
      /Connected|Disconnected|Mock data|Error|Syncing/,
    );

    // "Wearables" is an internal abstraction, not something the user configured.
    await expect(panel.getByText('Wearables', { exact: true })).toHaveCount(0);

    // Each row names the MCP server behind it and how it is reached.
    const rows = panel.locator('[data-testid^="source-"]');
    expect(await rows.count()).toBeGreaterThanOrEqual(2);
    await expect(panel.getByText(/read over (MCP|its REST API)|generated locally|read from a file export/).first()).toBeVisible();
  });

  test('chooses and reorders which MCPs supply the data', async ({ page }) => {
    await waitForTimeline(page);

    const before = await page.evaluate(async () =>
      (await (await fetch('/api/sources/selection')).json()).selected,
    );
    test.skip(before.length < 2, 'Needs at least two configured MCPs.');

    await page.getByTestId('source-picker-toggle').click();
    const popover = page.getByTestId('source-picker-popover');
    await expect(popover).toBeVisible();

    // Order is the merge priority, so moving one has to change the stored order.
    await page.getByTestId(`source-up-${before[1]}`).click();
    await expect
      .poll(async () =>
        page.evaluate(async () =>
          (await (await fetch('/api/sources/selection')).json()).selected.join(','),
        ),
      )
      .toBe([before[1], before[0]].join(','));

    // Switching one off removes it from the selection entirely.
    await page.getByTestId(`source-toggle-${before[0]}`).click();
    await expect
      .poll(async () =>
        page.evaluate(async () =>
          (await (await fetch('/api/sources/selection')).json()).selected,
        ),
      )
      .toEqual([before[1]]);

    // A source that was never contacted must not report itself as connected.
    const off = await page.evaluate(
      async (id) => {
        const body = await (await fetch('/api/data-sources')).json();
        return body.sources.filter((s: { id: string }) => s.id === id);
      },
      before[0],
    );
    for (const source of off) {
      expect(source.selected).toBe(false);
      expect(source.status).toBe('disconnected');
    }

    await page.evaluate(
      (selected) =>
        fetch('/api/sources/selection', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ selected }),
        }),
      before,
    );
  });

  test('draws lanes on one shared, aligned x-axis', async ({ page }) => {
    await waitForTimeline(page);

    await expect(page.getByText('12 AM').first()).toBeVisible();
    for (const label of ['3 AM', '6 AM', '9 AM', '12 PM', '3 PM', '6 PM', '9 PM']) {
      await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
    }

    const lanes = page.locator('[data-testid^="lane-plot-"]');
    const count = await lanes.count();
    expect(count).toBeGreaterThan(0);

    // Every lane plot must be exactly the same width, or the lanes do not line up.
    const widths = await lanes.evaluateAll((nodes) =>
      nodes.map((node) => node.querySelector('svg')?.getAttribute('width')),
    );
    expect(new Set(widths).size).toBe(1);
  });

  test('opens the details panel for an event and closes it again', async ({ page }) => {
    await waitForTimeline(page);

    const mark = page.locator('.tl-mark').first();
    await expect(mark).toBeVisible();
    const label = await mark.getAttribute('aria-label');
    expect(label).toBeTruthy();

    await mark.click();
    const panel = page.getByTestId('details-panel');
    await expect(panel).toBeVisible();

    // The panel must state provenance, not just a value.
    await expect(panel.getByText(/Measured directly|Derived feature/)).toBeVisible();
    await expect(panel.getByRole('button', { name: 'Inspect raw data' })).toBeVisible();

    await panel.getByRole('button', { name: 'Close details' }).click();
    await expect(panel).toBeHidden();
  });

  test('inspect raw data loads the underlying records', async ({ page }) => {
    await waitForTimeline(page);

    // Find a mark whose event has stored raw records behind it.
    const marks = page.locator('.tl-mark');
    const total = await marks.count();
    let opened = false;
    for (let index = 0; index < Math.min(total, 12); index += 1) {
      await marks.nth(index).click();
      const panel = page.getByTestId('details-panel');
      if (await panel.getByRole('button', { name: 'Inspect raw data' }).isVisible()) {
        await panel.getByRole('button', { name: 'Inspect raw data' }).click();
        await expect(panel.locator('table')).toBeVisible({ timeout: 15_000 });
        opened = true;
        break;
      }
    }
    expect(opened).toBe(true);
  });

  test('supports keyboard selection of a timeline mark', async ({ page }) => {
    await waitForTimeline(page);
    const mark = page.locator('.tl-mark').first();
    await mark.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('details-panel')).toBeVisible();
  });

  test('toggles collapsed and expanded, preserving the selection', async ({ page }) => {
    await waitForTimeline(page);

    await page.locator('.tl-mark').first().click();
    await expect(page.getByTestId('details-panel')).toBeVisible();
    const selectedTitle = await page
      .getByTestId('details-panel')
      .getByRole('heading', { level: 2 })
      .textContent();

    await page.getByTestId('mode-collapsed').click();
    await expect(page.getByTestId('timeline-collapsed')).toBeVisible();
    await expect(page.getByTestId('timeline-expanded')).toHaveCount(0);
    await expect(page.getByText('Major events')).toBeVisible();

    // The selection survives the mode change.
    await expect(page.getByTestId('details-panel').getByRole('heading', { level: 2 })).toHaveText(
      selectedTitle ?? '',
    );

    await page.getByTestId('mode-expanded').click();
    await expect(page.getByTestId('timeline-expanded')).toBeVisible();
    await expect(page.getByTestId('details-panel').getByRole('heading', { level: 2 })).toHaveText(
      selectedTitle ?? '',
    );
  });

  test('hides and restores a lane from the visible data streams control', async ({ page }) => {
    await waitForTimeline(page);

    const before = await page.locator('[data-testid^="lane-plot-"]').count();
    await page.getByTestId('stream-visibility-toggle').click();
    const popover = page.getByTestId('stream-visibility-popover');
    await expect(popover).toBeVisible();

    const firstCheckbox = popover.locator('input[type="checkbox"]').first();
    await firstCheckbox.uncheck();
    await expect(page.locator('[data-testid^="lane-plot-"]')).toHaveCount(before - 1);

    await firstCheckbox.check();
    await expect(page.locator('[data-testid^="lane-plot-"]')).toHaveCount(before);
  });

  test('refreshes the data without losing the page', async ({ page }) => {
    // A forced refresh drops the provider cache and re-reads every source.
    test.setTimeout(240_000);
    await waitForTimeline(page);
    // Refresh now targets the selected day's endpoint.
    const responsePromise = page.waitForResponse(
      (response) => /\/api\/(day\/[\d-]+|yesterday)\/sync/.test(response.url()) && response.status() === 200,
      { timeout: 120_000 },
    );
    await page.getByTestId('refresh-button').click();
    await responsePromise;
    await expect(page.getByTestId('timeline-expanded')).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId('status-card')).toBeVisible({ timeout: 90_000 });
  });

  test('makes no causal claims on the timeline itself', async ({ page }) => {
    // The DAG tab is explicitly a hypothesis view and is checked separately;
    // the timeline must still assert nothing causal.
    await waitForTimeline(page);
    const text = ((await page.locator('body').innerText()) ?? '').toLowerCase();
    for (const phrase of [
      'caused',
      'because of',
      'led to',
      'improved your',
      'great job',
      'good day',
      'poor sleep',
      'unhealthy',
    ]) {
      expect(text).not.toContain(phrase);
    }
  });

  test('the DAG never presents itself as an estimate', async ({ page }) => {
    await waitForTimeline(page);
    await page.getByTestId('mode-dag').click();
    await expect(page.getByTestId('timeline-dag')).toBeVisible();

    const payload = await page.evaluate(async () => {
      const response = await fetch('/api/dag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outcome: 'sleep_duration', exposure: 'exercise' }),
      });
      return response.json();
    });
    expect(payload.estimated).toBe(false);
    expect(payload.disclaimer).toMatch(/not an estimate/i);

    // The on-page disclaimer was removed at the owner's request, so the guard
    // is now that nothing on the page can be *read* as a measured result.
    const text = ((await page.locator('body').innerText()) ?? '').toLowerCase();
    for (const phrase of [
      'p =',
      'p-value',
      'effect size',
      'significant',
      'correlation',
      'caused',
    ]) {
      expect(text).not.toContain(phrase);
    }
  });

  test('keeps the timeline usable at a narrow laptop width', async ({ page }) => {
    await page.setViewportSize({ width: 1200, height: 860 });
    await waitForTimeline(page);
    await expect(page.getByTestId('timeline-expanded')).toBeVisible();

    // Lane labels stay readable rather than being dropped.
    const labels = page.locator('[data-testid^="lane-label-"]');
    expect(await labels.count()).toBeGreaterThan(0);
    await expect(labels.first()).toBeVisible();

    // The page itself must not scroll sideways; the timeline scrolls internally.
    const overflows = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(overflows).toBe(false);
  });
});
