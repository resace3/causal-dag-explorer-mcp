import { expect, test, type Page } from '@playwright/test';

/**
 * End-to-end run against the local backend (mock or live data).
 *
 * The assertions are written to hold for either, because the whole point of the
 * app is that it reports honestly whatever the configured sources returned.
 */

/**
 * Snapshot the user-drawn arrows, and afterwards remove whatever is new.
 *
 * A drag that misses its intended tier still writes a real edge, so a cleanup
 * naming the expected pair leaves that miss behind to change the graph every
 * later test sees. Diffing against a snapshot removes exactly what the test
 * caused, and never an arrow the person drew themselves.
 */
const USER_EDGE_HELPERS = `
  // The page opens on today, so anything comparing the API against what is on
  // screen has to ask for the same day the page asked for.
  window.displayedDay = async () => {
    const days = await (await fetch('/api/days')).json();
    return await (await fetch('/api/day/' + days.today)).json();
  };
  window.userEdgeKeys = async () => {
    const body = await (await fetch('/api/dag/edges')).json();
    return body.edges.filter((e) => e.origin === 'user').map((e) => e.source + '|' + e.target);
  };
  window.removeUserEdgesNotIn = async (keep) => {
    const keys = await window.userEdgeKeys();
    let removed = 0;
    for (const key of keys) {
      if (keep.includes(key)) continue;
      const [source, target] = key.split('|');
      await fetch(\`/api/dag/edges/\${source}/\${target}\`, { method: 'DELETE' });
      removed += 1;
    }
    return removed;
  };
`;

declare global {
  interface Window {
    displayedDay: () => Promise<any>;
    userEdgeKeys: () => Promise<string[]>;
    removeUserEdgesNotIn: (keep: string[]) => Promise<number>;
  }
}

async function waitForTimeline(page: Page) {
  await page.addInitScript(USER_EDGE_HELPERS);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Today', level: 1 })).toBeVisible();
  await expect(page.getByTestId('status-card')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('timeline-expanded')).toBeVisible({ timeout: 30_000 });
}

test.describe('Yesterday timeline', () => {
  test('renders the page shell with Today as the only navigation item', async ({ page }) => {
    await waitForTimeline(page);

    const nav = page.getByRole('navigation', { name: 'Main navigation' });
    await expect(nav.getByRole('button')).toHaveCount(1);
    await expect(page.getByTestId('nav-today')).toHaveAttribute('aria-current', 'page');

    for (const forbidden of ['Home', 'Trends', 'Insights', 'Settings', 'Reports']) {
      await expect(nav.getByText(forbidden, { exact: true })).toHaveCount(0);
    }

    await expect(page.getByText('Your data from today so far, from 12:00 AM')).toBeVisible();
    await expect(page.getByText('All times shown in your local time')).toBeVisible();
  });

  test('picks another day from the calendar', async ({ page }) => {
    await waitForTimeline(page);

    const heading = page.getByRole('heading', { level: 1 });
    await expect(heading).toHaveText('Today');

    // Pick the latest earlier day the calendar is actually showing, rather
    // than counting back a fixed number of days: the calendar renders one
    // month, so on the 2nd of a month arithmetic lands on a date that is not
    // on screen, and the failure looks like a broken calendar instead of a
    // test that walked off the page.
    const today = await page.evaluate(async () => {
      const response = await fetch('/api/days');
      return (await response.json()).today as string;
    });
    const iso = await page
      .locator('[data-testid^="calendar-day-"]:not([disabled])')
      .evaluateAll(
        (nodes, current: string) =>
          nodes
            .map((node) => (node as HTMLElement).dataset.testid!.replace('calendar-day-', ''))
            .filter((date) => date < current)
            .sort()
            .pop() ?? '',
        today,
      );
    expect(iso, 'the calendar must offer at least one earlier day').not.toBe('');

    await page.getByTestId(`calendar-day-${iso}`).click();
    await expect(heading).not.toHaveText('Today', { timeout: 60_000 });
    await expect(page.getByTestId('timeline-expanded').or(page.getByText(/No data source/))).toBeVisible({
      timeout: 60_000,
    });

    // The Today item goes back.
    await page.getByTestId('nav-today').click();
    await expect(heading).toHaveText('Today', { timeout: 60_000 });
  });

  test('shows the whole model, with no question to configure first', async ({ page }) => {
    await waitForTimeline(page);

    await page.getByTestId('mode-dag').click();
    const dag = page.getByTestId('timeline-dag');
    await expect(dag).toBeVisible();
    await expect(dag.locator('[data-testid^="dag-node-"]').first()).toBeVisible({
      timeout: 30_000,
    });

    // Nothing to pick before there is a graph, and no mode to enter before an
    // arrow can be drawn.
    await expect(page.getByTestId('dag-outcome')).toHaveCount(0);
    await expect(page.getByTestId('dag-exposure')).toHaveCount(0);
    await expect(page.getByTestId('dag-edit-toggle')).toHaveCount(0);

    // The rows are the timeline's rows and nothing else: no variable of a lane
    // this day has no data for, and none of the ones no lane observes at all.
    await expect(dag.getByTestId('dag-row-stress')).toHaveCount(0);
    await expect(dag.getByTestId('dag-row-alcohol')).toHaveCount(0);

    const laneIds = await page.evaluate(async () => {
      const body = await window.displayedDay();
      return body.lanes
        .filter((lane: { available: boolean }) => lane.available)
        .map((lane: { id: string }) => lane.id);
    });
    const rowLanes = await dag
      .locator('[data-testid^="dag-row-"]')
      .evaluateAll((nodes) => nodes.map((node) => (node.textContent ?? '').trim()));
    expect(rowLanes.length).toBeGreaterThan(0);
    expect(laneIds.length).toBeGreaterThan(0);

    // A node opens its own explanation.
    await dag.locator('[data-testid^="dag-node-"]').first().click();
    await expect(dag.getByTestId('dag-node-detail')).toBeVisible();

    // Switching back leaves the timeline intact.
    await page.getByTestId('mode-expanded').click();
    await expect(page.getByTestId('timeline-expanded')).toBeVisible();
  });

  test('has exactly the expanded tab\u2019s rows, with the same names in the same order', async ({
    page,
  }) => {
    await waitForTimeline(page);

    const read = (selector: string) =>
      page.locator(selector).evaluateAll((nodes) =>
        nodes.map((node) => ({
          id: (node as HTMLElement).dataset.testid ?? '',
          name: node.querySelector('span.font-semibold')?.textContent?.trim() ?? '',
        })),
      );

    const expanded = (await read('[data-testid^="lane-label-"]')).map((row) => ({
      id: row.id.replace('lane-label-', ''),
      name: row.name,
    }));
    expect(expanded.length).toBeGreaterThan(0);

    await page.getByTestId('mode-dag').click();
    await expect(page.locator('[data-testid^="dag-row-"]').first()).toBeVisible({
      timeout: 60_000,
    });
    const dagRows = (await read('[data-testid^="dag-row-"]')).map((row) => ({
      id: row.id.replace('dag-row-', ''),
      name: row.name,
    }));

    // Not a subset, not a superset, not reordered: the same rows.
    expect(dagRows).toEqual(expanded);

    // And the model really does hold variables that were left out, or the
    // check above would pass simply because nothing extra came back.
    const omitted = await page.evaluate(async () => {
      const day = await window.displayedDay();
      const dag = await (
        await fetch('/api/dag', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ day: day.date }),
        })
      ).json();
      const drawn = new Set(
        day.lanes.filter((l: { available: boolean }) => l.available).map((l: { id: string }) => l.id),
      );
      return (dag.timeline?.rows ?? []).filter(
        (row: { lane: string | null }) => !row.lane || !drawn.has(row.lane),
      ).length;
    });
    expect(omitted).toBeGreaterThan(0);
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
    //
    // The stream is chosen from what this day actually holds rather than
    // named outright: a threshold needs a numeric series, and which sources
    // publish one varies by day — a wearable that reports a single resting
    // heart rate for the day offers no curve to compare against, and the app
    // is right to refuse that rather than invent one.
    const stream = await page.evaluate(async () => {
      const body = await window.displayedDay();
      for (const lane of body.lanes) {
        for (const series of lane.series ?? []) {
          if ((series.points ?? []).length > 2) return series.label as string;
        }
      }
      return null;
    });
    test.skip(!stream, 'This day published no continuous series to threshold against.');

    await page.getByTestId('add-row-prompt').fill(`${stream} below 50`);
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
    await page.setViewportSize({ width: 1400, height: 1200 });
    await waitForTimeline(page);
    await page.getByTestId('mode-dag').click();
    const dag = page.getByTestId('timeline-dag');
    await expect(dag).toBeVisible();
    await expect(dag.locator('[data-testid^="dag-row-"]').first()).toBeVisible({
      timeout: 30_000,
    });

    // Both ends have to be variables the day is drawing, since the rows are now
    // exactly the timeline's — and the model must hold no arrow between them
    // in either direction, or the drag would be refused as a duplicate rather
    // than drawn. Naming a fixed pair meant this test quietly skipped itself
    // the day one of them stopped being observed, so the pair is chosen from
    // what is actually on screen.
    const edgesBefore = await page.evaluate(() => userEdgeKeys());
    const pair = await page.evaluate(async () => {
      const drawn = [...document.querySelectorAll('[data-testid^="dag-handle-"]')].map(
        (node) => (node as HTMLElement).dataset.testid!.replace('dag-handle-', ''),
      );
      const body = await (await fetch('/api/dag/edges')).json();
      const linked = new Set(
        body.edges.flatMap((e: { source: string; target: string }) => [
          `${e.source}|${e.target}`,
          `${e.target}|${e.source}`,
        ]),
      );
      for (const a of drawn) {
        for (const b of drawn) {
          if (a !== b && !linked.has(`${a}|${b}`)) return [a, b];
        }
      }
      return null;
    });
    test.skip(!pair, 'This day drew fewer than two unconnected variables.');
    const [source, target] = pair!;

    const handle = page.getByTestId(`dag-handle-${source}`).locator('visible=true').first();
    await handle.scrollIntoViewIfNeeded();
    const from = await handle.boundingBox();
    expect(from).not.toBeNull();

    await page.mouse.move(from!.x + from!.width / 2, from!.y + from!.height / 2);
    await page.mouse.down();
    await page.mouse.move(from!.x + 150, from!.y + 40, { steps: 10 });

    // Whole rows are the drop target, and only exist mid-drag.
    const drop = page.getByTestId(`dag-drop-${target}`);
    await expect(drop).toBeAttached({ timeout: 10_000 });
    await drop.scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);

    // Twice, re-reading the box between: a pointer near the edge of the window
    // makes the view auto-scroll itself — which is what lets a drag reach a row
    // off the bottom — so the first position can be stale by the time the
    // pointer arrives, and the release then lands on no row at all.
    for (const steps of [10, 4]) {
      const to = await drop.boundingBox();
      expect(to).not.toBeNull();
      await page.mouse.move(to!.x + to!.width / 2, to!.y + to!.height / 2, { steps });
      await page.waitForTimeout(150);
    }
    await page.mouse.up();

    // The arrow is now in the model, and labelled as the user's.
    await expect
      .poll(
        async () =>
          page.evaluate(
            async ([a, b]) => {
              const body = await (await fetch('/api/dag/edges')).json();
              return body.edges.filter(
                (edge: { source: string; target: string }) =>
                  edge.source === a && edge.target === b,
              ).length;
            },
            [source, target],
          ),
        { timeout: 20_000 },
      )
      .toBe(1);

    // Clean up so the run is repeatable: whatever this test added, whether or
    // not it was the pair asked for.
    await page.evaluate((keep) => removeUserEdgesNotIn(keep), edgesBefore);
  });

  test('refuses a dragged arrow that would create a cycle, and says why', async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 1200 });
    await waitForTimeline(page);
    const edgesBefore = await page.evaluate(() => userEdgeKeys());
    await page.getByTestId('mode-dag').click();
    await expect(page.getByTestId('dag-row-activity')).toBeVisible({ timeout: 30_000 });

    // exercise -> step_count is in the model, so the reverse closes a loop.
    // Both share the Activity lane, so both are on screen together.
    //
    // A variable can carry more than one handle, so the visible one is picked
    // rather than whichever comes first in the DOM: pressing on a handle that
    // is scrolled out of view starts no drag, and the failure then surfaces
    // much later as a missing drop row.
    const handle = page
      .getByTestId('dag-handle-step_count')
      .locator('visible=true')
      .first();
    await handle.scrollIntoViewIfNeeded();
    await expect(handle).toBeVisible();
    const from = await handle.boundingBox();
    await page.mouse.move(from!.x + from!.width / 2, from!.y + from!.height / 2);
    await page.mouse.down();
    await page.mouse.move(from!.x + 120, from!.y + 30, { steps: 8 });

    // Drop rows only exist mid-drag, so their presence is the proof that the
    // press above actually began one.
    const dropRow = page.getByTestId('dag-drop-exercise');
    await expect(dropRow).toBeVisible({ timeout: 10_000 });
    const to = await dropRow.boundingBox();
    await page.mouse.move(to!.x + to!.width / 2, to!.y + to!.height / 2, { steps: 8 });
    await page.mouse.up();

    const error = page.getByTestId('dag-edit-error');
    await expect(error).toBeVisible({ timeout: 20_000 });
    await expect(error).toContainText(/cycle/i);

    // A refused drag writes nothing, but a drag that missed the intended tier
    // would have written something real. Leave no arrow behind either way.
    await page.evaluate((keep) => removeUserEdgesNotIn(keep), edgesBefore);
  });

  test('keeps the DAG to the graph itself, with no prose below it', async ({ page }) => {
    await waitForTimeline(page);
    await page.getByTestId('mode-dag').click();
    const dag = page.getByTestId('timeline-dag');
    await expect(dag.locator('[data-testid^="dag-row-"]').first()).toBeVisible({
      timeout: 30_000,
    });

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

  test('draws computer use as its own lane, down to the rule behind a mark', async ({ page }) => {
    await waitForTimeline(page);

    const plot = page.getByTestId('lane-plot-computer_use');
    // ActivityWatch holds nothing from before it was installed, so on a live
    // install the displayed day can legitimately predate it. A lane that hides
    // itself and says why is the correct behaviour there, and is covered by the
    // backend suite; there is nothing to draw for this test to check.
    test.skip(
      (await plot.count()) === 0,
      'ActivityWatch recorded nothing for the displayed day.',
    );

    await expect(page.getByTestId('lane-label-computer_use')).toContainText('Computer Use');
    const marks = plot.locator('.tl-mark');
    // Three tiers — at the machine, in an application, on a site — so a lane
    // with only one kind of mark means two of them silently stopped rendering.
    expect(await marks.count()).toBeGreaterThan(2);

    await marks.first().click();
    const panel = page.getByTestId('details-panel');
    await expect(panel).toBeVisible();
    await expect(panel.getByText(/computer_use\./)).toBeVisible();
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

    // Order is the merge priority, so moving one has to change the stored
    // order. Only the two it swaps are named: any further sources keep their
    // places, and asserting the whole list against a two-source install is how
    // this test broke when a third MCP was connected.
    const rest = before.slice(2);
    await page.getByTestId(`source-up-${before[1]}`).click();
    await expect
      .poll(async () =>
        page.evaluate(async () =>
          (await (await fetch('/api/sources/selection')).json()).selected.join(','),
        ),
      )
      .toBe([before[1], before[0], ...rest].join(','));

    // Switching one off removes it from the selection entirely.
    await page.getByTestId(`source-toggle-${before[0]}`).click();
    await expect
      .poll(async () =>
        page.evaluate(async () =>
          (await (await fetch('/api/sources/selection')).json()).selected,
        ),
      )
      .toEqual([before[1], ...rest]);

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

  test('draws the phone rows, the followed app directly under the one it is part of', async ({
    page,
  }) => {
    await waitForTimeline(page);

    const laneIds = async (prefix: string) =>
      page
        .locator(`[data-testid^="${prefix}"]`)
        .evaluateAll((nodes, strip: string) =>
          nodes.map((node) => node.getAttribute('data-testid')!.slice(strip.length)),
        prefix);

    const rows = await laneIds('lane-label-');
    test.skip(!rows.includes('phone_use'), 'this day recorded no phone use');

    const plot = page.getByTestId('lane-plot-phone_use');
    await expect(plot).toBeVisible();
    // The row states what it measured rather than only drawing it.
    await expect(plot.getByText(/with the screen on/)).toBeVisible();

    if (!rows.includes('tiktok')) return;

    // The followed app is a subset of phone use, not a parallel measurement, so
    // it sits directly beneath the row it came out of — on both tabs.
    expect(rows.indexOf('tiktok')).toBe(rows.indexOf('phone_use') + 1);

    await page.getByTestId('mode-dag').click();
    await expect(page.getByTestId('dag-row-phone_use')).toBeVisible({ timeout: 30_000 });
    const dagRows = await laneIds('dag-row-');
    expect(dagRows.indexOf('tiktok')).toBe(dagRows.indexOf('phone_use') + 1);
  });

  test('the TV row says the set was on without claiming it was watched', async ({
    page,
  }) => {
    await waitForTimeline(page);

    const rows = await page
      .locator('[data-testid^="lane-label-"]')
      .evaluateAll((nodes) =>
        nodes.map((node) => node.getAttribute('data-testid')!.slice('lane-label-'.length)),
      );
    test.skip(!rows.includes('tv'), 'this day recorded no television use');

    const plot = page.getByTestId('lane-plot-tv');
    await expect(plot).toBeVisible();
    // "On" is the only claim the power sensor supports. A summary that said
    // "watching" would be the row overstating what it measured.
    await expect(plot.getByText(/with the TV on/)).toBeVisible();
    await expect(plot.getByText(/watching/)).toHaveCount(0);

    // The details panel has to carry the same caveat, since that is where
    // someone goes to find out what the bar actually means.
    await plot.locator('.tl-mark').first().click();
    await expect(
      page.getByText(/Powered on is not the same as watched/),
    ).toBeVisible();
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
    // Exact: the "Major events only" switch beside it is a different control.
    await expect(page.getByText('Major events', { exact: true })).toBeVisible();

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

  test('opens a collapsed mark from its caption, including one from another day', async ({
    page,
  }) => {
    await waitForTimeline(page);
    await page.getByTestId('mode-collapsed').click();
    await expect(page.getByTestId('collapsed-phenotypes')).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(2000);

    const marks = page.locator('[data-testid="collapsed-scroller"] .tl-mark');
    expect(await marks.count()).toBeGreaterThan(0);

    // The caption is the most obvious thing to click, and it used to sit in a
    // group that ignored pointer events — so clicking an event's own name did
    // nothing at all.
    const captioned = marks.filter({ has: page.locator('text') }).first();
    await captioned.scrollIntoViewIfNeeded();
    const caption = captioned.locator('text').first();
    await expect(caption).toBeVisible();
    await caption.click();
    await expect(page.getByTestId('details-panel')).toBeVisible();

    // A mark can belong to any day in the two-month window. The page used to
    // re-resolve every selection against the day it was displaying, fail to
    // find one from a neighbour, and close the panel the instant it opened.
    const otherDay = page.getByTestId('details-other-day');
    const dayCount = await page.locator('[data-testid^="collapsed-day-"]').count();
    if (dayCount > 1 || (await otherDay.count())) {
      const heading = await page
        .getByTestId('details-panel')
        .getByRole('heading', { level: 2 })
        .textContent();
      expect(heading?.trim()).toBeTruthy();
      // When it is from another day, the panel has to say so rather than
      // showing its times under the heading of the day on screen.
      if (await otherDay.count()) {
        await expect(otherDay).toContainText(/not the day on screen/);
      }
    }
  });

  test('comes back to the tab you were on', async ({ page }) => {
    await waitForTimeline(page);
    await page.getByTestId('mode-collapsed').click();
    await expect(page.getByTestId('timeline-collapsed')).toBeVisible();

    await page.reload();
    await expect(page.getByTestId('timeline-collapsed')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('timeline-expanded')).toHaveCount(0);

    await page.getByTestId('mode-expanded').click();
    await expect(page.getByTestId('timeline-expanded')).toBeVisible();
    await page.reload();
    await expect(page.getByTestId('timeline-expanded')).toBeVisible({ timeout: 60_000 });
  });

  test('can bring anything from the expanded tab onto the collapsed one', async ({ page }) => {
    await waitForTimeline(page);

    // Lanes holding at least one event. A lane that is only a continuous line
    // is excluded on purpose: one row of marks cannot draw a curve, and picking
    // a moment out of it to stand for the whole would be inventing salience.
    const expandedLanes = await page.evaluate(async () => {
      const body = await window.displayedDay();
      return body.lanes
        .filter((lane: { available: boolean; events: unknown[] }) => lane.available && lane.events.length)
        .map((lane: { id: string }) => lane.id);
    });
    expect(expandedLanes.length).toBeGreaterThan(0);

    await page.getByTestId('mode-collapsed').click();
    await expect(page.getByTestId('timeline-collapsed')).toBeVisible();
    await expect(page.getByTestId('collapsed-phenotypes')).toBeVisible({ timeout: 30_000 });

    // Every one of them has a switch here, whether or not its events are in the
    // curated "major" list.
    for (const laneId of expandedLanes) {
      await expect(page.getByTestId(`collapsed-toggle-${laneId}`)).toBeVisible();
    }

    // A lane that is off can be switched on, and then draws something.
    // Resolved to a fixed testid first: a locator selecting on aria-pressed
    // stops matching the moment the click lands and silently re-resolves to
    // the next switched-off lane.
    const offId = await page
      .locator('[data-testid^="collapsed-toggle-"][aria-pressed="false"]')
      .first()
      .getAttribute('data-testid')
      .catch(() => null);

    if (offId) {
      const toggle = page.getByTestId(offId);
      const before = await page.locator('[data-testid="collapsed-scroller"] .tl-mark').count();
      await toggle.click();
      await expect(toggle).toHaveAttribute('aria-pressed', 'true');
      await expect
        .poll(async () => page.locator('[data-testid="collapsed-scroller"] .tl-mark').count())
        .toBeGreaterThan(before);
      await toggle.click();
      await expect(toggle).toHaveAttribute('aria-pressed', 'false');
    }

    // And the curation itself can be dropped for everything the lanes hold.
    //
    // The count is asserted not to *fall*, rather than to rise: on a day whose
    // lanes happen to hold only major events there is genuinely nothing extra
    // to reveal, and a test demanding more would be demanding data. What must
    // hold on every day is that the switch flips and the row says which of the
    // two it is showing.
    const all = page.getByTestId('collapsed-all-events');
    const before = await page.locator('[data-testid="collapsed-scroller"] .tl-mark').count();
    await expect(page.getByText('Major events', { exact: true })).toBeVisible();

    await all.click();
    await expect(all).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByText('Every event', { exact: true }).first()).toBeVisible();
    await expect
      .poll(async () => page.locator('[data-testid="collapsed-scroller"] .tl-mark').count())
      .toBeGreaterThanOrEqual(before);

    await all.click();
    await expect(all).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByText('Major events', { exact: true })).toBeVisible();
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

  test('a row hidden on Expanded is gone from Collapsed and the DAG too', async ({ page }) => {
    await waitForTimeline(page);

    // A lane with events, so it has a switch on the collapsed tab to lose, and
    // one the DAG draws rows for, so there is something there to lose as well.
    // Computer Use qualifies for the first and not the second: no variable in
    // the causal model is observed through it.
    const laneId = await page.evaluate(async () => {
      const day = await window.displayedDay();
      const dag = await (
        await fetch('/api/dag', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ day: day.date }),
        })
      ).json();
      const withRows = new Set(
        (dag.timeline?.rows ?? []).map((row: { lane: string | null }) => row.lane),
      );
      const lane = day.lanes.find(
        (item: { available: boolean; events: unknown[]; id: string }) =>
          item.available && item.events.length && withRows.has(item.id),
      );
      return lane?.id ?? null;
    });
    test.skip(!laneId, 'No lane on this day carries both events and a causal variable.');

    // Confirm it is offered everywhere before hiding it, or the assertions
    // below would pass against a lane that was never there.
    await page.getByTestId('mode-collapsed').click();
    await expect(page.getByTestId(`collapsed-toggle-${laneId}`)).toBeVisible({ timeout: 30_000 });
    await page.getByTestId('mode-dag').click();
    await expect(page.locator('[data-testid^="dag-row-"]').first()).toBeVisible({
      timeout: 60_000,
    });
    const dagRowsBefore = await page
      .locator('[data-testid^="dag-row-"]')
      .evaluateAll((nodes) =>
        nodes.map((node) => (node as HTMLElement).dataset.testid!.replace('dag-row-', '')),
      );

    await page.getByTestId('mode-expanded').click();
    await expect(page.getByTestId('timeline-expanded')).toBeVisible();
    await page.getByTestId('stream-visibility-toggle').click();
    await page.getByTestId(`stream-visibility-${laneId}`).uncheck();
    await expect(page.getByTestId(`lane-plot-${laneId}`)).toHaveCount(0);
    await page.keyboard.press('Escape');

    // Collapsed: no switch at all, not merely a switch turned off.
    await page.getByTestId('mode-collapsed').click();
    await expect(page.getByTestId('timeline-collapsed')).toBeVisible();
    await expect(page.getByTestId(`collapsed-toggle-${laneId}`)).toHaveCount(0);

    // DAG: the variables observed through that lane lose their rows, and the
    // rows belonging to lanes still on the timeline are untouched.
    await page.getByTestId('mode-dag').click();
    await expect(page.locator('[data-testid^="dag-row-"]').first()).toBeVisible({
      timeout: 60_000,
    });
    const dagRowsAfter = await page
      .locator('[data-testid^="dag-row-"]')
      .evaluateAll((nodes) =>
        nodes.map((node) => (node as HTMLElement).dataset.testid!.replace('dag-row-', '')),
      );
    expect(dagRowsAfter.length).toBeLessThan(dagRowsBefore.length);
    expect(dagRowsAfter.every((row) => dagRowsBefore.includes(row))).toBe(true);

    // Restoring it brings all three back.
    await page.getByTestId('mode-expanded').click();
    await page.getByTestId('stream-visibility-toggle').click();
    await page.getByTestId(`stream-visibility-${laneId}`).check();
    await expect(page.getByTestId(`lane-plot-${laneId}`)).toBeVisible();
    await page.keyboard.press('Escape');

    await page.getByTestId('mode-collapsed').click();
    await expect(page.getByTestId(`collapsed-toggle-${laneId}`)).toBeVisible();
    await page.getByTestId('mode-dag').click();
    await expect
      .poll(async () => page.locator('[data-testid^="dag-row-"]').count(), { timeout: 30_000 })
      .toBe(dagRowsBefore.length);
  });

  test('remembers a hidden row across a reload and into another tab', async ({ page, context }) => {
    await waitForTimeline(page);

    const before = await page.locator('[data-testid^="lane-plot-"]').count();
    test.skip(before < 2, 'Needs at least two lanes to hide one.');

    // Hide the second row from its own × — the control that made the arrangement.
    const hiddenId = await page
      .locator('[data-testid^="lane-label-"]')
      .nth(1)
      .evaluate((node) => (node as HTMLElement).dataset.testid!.replace('lane-label-', ''));
    await page.getByTestId(`lane-label-${hiddenId}`).hover();
    await page.getByTestId(`lane-hide-${hiddenId}`).click();
    await expect(page.getByTestId(`lane-plot-${hiddenId}`)).toHaveCount(0);

    // A reload must not quietly bring it back: the arrangement is the user's,
    // and one that resets is a control not worth using.
    await page.reload();
    await expect(page.getByTestId('timeline-expanded')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId(`lane-plot-${hiddenId}`)).toHaveCount(0);

    // Nor may a second tab show a different arrangement of the same day.
    const other = await context.newPage();
    try {
      await other.goto('/');
      await expect(other.getByTestId('timeline-expanded')).toBeVisible({ timeout: 60_000 });
      await expect(other.getByTestId(`lane-plot-${hiddenId}`)).toHaveCount(0);

      // Restoring it in one tab reaches the other, so the older tab cannot
      // later write its stale arrangement back over this one.
      await other.getByTestId('stream-visibility-toggle').click();
      await other.getByTestId(`stream-visibility-${hiddenId}`).check();
      await expect(other.getByTestId(`lane-plot-${hiddenId}`)).toBeVisible();
      await expect(page.getByTestId(`lane-plot-${hiddenId}`)).toBeVisible({ timeout: 15_000 });
    } finally {
      await other.close();
    }
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
