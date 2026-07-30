import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Timeline } from '../src/timeline/Timeline';
import { CollapsedTimeline, majorEvents } from '../src/timeline/CollapsedTimeline';
import { DetailsPanel } from '../src/details/DetailsPanel';
import { TimelineControls } from '../src/components/TimelineControls';
import { Sidebar } from '../src/components/Sidebar';
import { PageHeader } from '../src/components/PageHeader';
import { SourceNotices, TimelineSkeleton } from '../src/components/States';
import { makeEvent, makeLane, makeSeries, makeTimeline } from './fixtures';
import type { DayTimeline, Selection } from '../src/types/timeline';

const DAY_PROPS = {
  selectedDate: '2025-06-10',
  yesterday: '2025-06-10',
  today: '2025-06-11',
  dayIndex: new Map(),
  onSelectDate: () => {},
};

function renderTimeline(overrides = {}) {
  const timeline = makeTimeline(overrides);
  const lanes = timeline.lanes.filter((lane) => lane.available);
  const onSelect = vi.fn();
  render(
    <Timeline
      timeline={timeline}
      lanes={lanes}
      selectedKey={null}
      onSelect={onSelect}
      zoom={1}
    />,
  );
  return { timeline, lanes, onSelect };
}

describe('expanded timeline', () => {
  it('renders one row per available lane', () => {
    const { lanes } = renderTimeline();
    for (const lane of lanes) {
      expect(screen.getByTestId(`lane-label-${lane.id}`)).toBeInTheDocument();
      expect(screen.getByTestId(`lane-plot-${lane.id}`)).toBeInTheDocument();
    }
    // The unavailable HRV lane was filtered out before rendering.
    expect(screen.queryByTestId('lane-label-hrv')).not.toBeInTheDocument();
  });

  it('gives every lane the same plot width so lanes stay aligned', () => {
    const { lanes } = renderTimeline();
    const widths = lanes.map(
      (lane) =>
        screen.getByTestId(`lane-plot-${lane.id}`).querySelector('svg')?.getAttribute('width'),
    );
    expect(new Set(widths).size).toBe(1);
  });

  it('shows the lane name and its short description', () => {
    renderTimeline();
    const label = screen.getByTestId('lane-label-activity');
    expect(within(label).getByText('Activity')).toBeInTheDocument();
    expect(within(label).getByText('Exercise and movement')).toBeInTheDocument();
  });

  it('describes each event for screen readers', () => {
    renderTimeline();
    const mark = screen.getByRole('button', { name: /Morning workout/ });
    expect(mark).toHaveAttribute(
      'aria-label',
      expect.stringContaining('7:15 AM – 8:00 AM'),
    );
    expect(mark.getAttribute('aria-label')).toContain('measured');
  });

  it('selects an event when it is clicked', async () => {
    const { onSelect } = renderTimeline();
    await userEvent.click(screen.getByRole('button', { name: /Morning workout/ }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    const selection = onSelect.mock.calls[0][0] as Selection;
    expect(selection.kind).toBe('event');
    expect(selection.laneId).toBe('activity');
  });

  it('selects an event from the keyboard', async () => {
    const { onSelect } = renderTimeline();
    screen.getByRole('button', { name: /Morning workout/ }).focus();
    await userEvent.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalled();
  });

  it('marks an interval that crosses midnight as continuing', () => {
    renderTimeline();
    const label = screen
      .getByRole('button', { name: /Main sleep/ })
      .getAttribute('aria-label');
    expect(label).toContain('continues from the previous day');
  });

  it('draws a missing-data gap rather than bridging it', () => {
    const timeline = makeTimeline({
      lanes: [
        makeLane({
          id: 'heart_rate',
          phenotype: 'heart_rate',
          label: 'Heart Rate',
          description: 'Wearable cardiovascular signal',
          accent: 'blue',
          events: [],
          series: [
            makeSeries({
              gaps: [
                {
                  startTime: '2025-06-10T13:00:00-04:00',
                  endTime: '2025-06-10T17:30:00-04:00',
                  reason: 'The wearable recorded no heart rate here.',
                },
              ],
            }),
          ],
        }),
      ],
    });
    render(
      <Timeline
        timeline={timeline}
        lanes={timeline.lanes}
        selectedKey={null}
        onSelect={vi.fn()}
        zoom={1}
      />,
    );
    expect(screen.getByText('No data')).toBeInTheDocument();
    // The line is split into separate paths on either side of the gap.
    const plot = screen.getByTestId('lane-plot-heart_rate');
    const strokes = plot.querySelectorAll('path[stroke]');
    expect(strokes.length).toBeGreaterThanOrEqual(2);
  });

  it('widens the plot when zoomed', () => {
    const timeline = makeTimeline();
    const { rerender } = render(
      <Timeline
        timeline={timeline}
        lanes={timeline.lanes.filter((lane) => lane.available)}
        selectedKey={null}
        onSelect={vi.fn()}
        zoom={1}
      />,
    );
    const before = Number(
      screen.getByTestId('lane-plot-activity').querySelector('svg')?.getAttribute('width'),
    );
    rerender(
      <Timeline
        timeline={timeline}
        lanes={timeline.lanes.filter((lane) => lane.available)}
        selectedKey={null}
        onSelect={vi.fn()}
        zoom={2}
      />,
    );
    const after = Number(
      screen.getByTestId('lane-plot-activity').querySelector('svg')?.getAttribute('width'),
    );
    expect(after).toBeCloseTo(before * 2, 0);
  });
});

describe('collapsed timeline', () => {
  it('keeps only the major events', () => {
    const lanes = [
      makeLane({
        events: [
          makeEvent({ id: 'a', category: 'strength_training' }),
          makeEvent({ id: 'b', category: 'motion', label: 'Motion — kitchen' }),
        ],
      }),
    ];
    const major = majorEvents(lanes);
    expect(major.map((item) => item.event.id)).toEqual(['a']);
  });

  it('ignores lanes with no data', () => {
    const lanes = [
      makeLane({ available: false, events: [makeEvent({ category: 'strength_training' })] }),
    ];
    expect(majorEvents(lanes)).toHaveLength(0);
  });

  const asRange = (timeline: DayTimeline) => [
    { date: timeline.date, timeline, status: 'loaded' as const, stored: true },
  ];

  it('renders the major events on the shared axis without causal arrows', () => {
    const timeline = makeTimeline();
    render(
      <CollapsedTimeline
        days={asRange(timeline)}
        focusDate={timeline.date}
        hidden={new Set()}
        onTogglePhenotype={vi.fn()}
        selectedKey={null}
        onSelect={vi.fn()}
        zoom={1}
        onLoadDay={vi.fn()}
      />,
    );
    expect(screen.getByTestId('timeline-collapsed')).toBeInTheDocument();
    expect(screen.getByText('Major events')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Morning workout/ })).toBeInTheDocument();

    // No connectors between events: nothing may imply a causal path.
    const svg = screen.getByRole('group', { name: /Collapsed timeline/ });
    expect(svg.querySelectorAll('marker')).toHaveLength(0);
    expect(svg.querySelectorAll('[marker-end]')).toHaveLength(0);
  });

  it('hides a phenotype when its toggle is switched off', () => {
    const timeline = makeTimeline();
    const { rerender } = render(
      <CollapsedTimeline
        days={asRange(timeline)}
        focusDate={timeline.date}
        hidden={new Set()}
        onTogglePhenotype={vi.fn()}
        selectedKey={null}
        onSelect={vi.fn()}
        zoom={1}
        onLoadDay={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: /Morning workout/ })).toBeInTheDocument();

    rerender(
      <CollapsedTimeline
        days={asRange(timeline)}
        focusDate={timeline.date}
        hidden={new Set(['activity'])}
        onTogglePhenotype={vi.fn()}
        selectedKey={null}
        onSelect={vi.fn()}
        zoom={1}
        onLoadDay={vi.fn()}
      />,
    );
    expect(screen.queryByRole('button', { name: /Morning workout/ })).not.toBeInTheDocument();
    // The toggle itself stays, so the phenotype can be brought back.
    expect(screen.getByTestId('collapsed-toggle-activity')).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('offers to fetch a day that has not been reconstructed, without doing it unasked', () => {
    const timeline = makeTimeline();
    const onLoadDay = vi.fn();
    render(
      <CollapsedTimeline
        days={[
          { date: '2026-07-01', timeline: null, status: 'unfetched', stored: false },
          ...asRange(timeline),
        ]}
        focusDate={timeline.date}
        hidden={new Set()}
        onTogglePhenotype={vi.fn()}
        selectedKey={null}
        onSelect={vi.fn()}
        zoom={1}
        onLoadDay={onLoadDay}
      />,
    );

    // Nothing is fetched merely by widening the window.
    expect(onLoadDay).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('collapsed-load-2026-07-01'));
    expect(onLoadDay).toHaveBeenCalledWith('2026-07-01');
  });

  describe('a period that crosses midnight', () => {
    /**
     * One night's sleep is stored once per day it touches, each copy cut at the
     * boundary. Drawn naively that is two capsules with a gap between them,
     * describing an awakening that never happened.
     */
    const nightAcrossMidnight = () => {
      const evening = makeTimeline({
        date: '2025-06-10',
        lanes: [
          makeLane({
            id: 'sleep',
            phenotype: 'sleep',
            label: 'Sleep',
            accent: 'orange',
            events: [
              makeEvent({
                id: 'sleep_evening',
                label: 'Main sleep',
                category: 'main_sleep',
                startTime: '2025-06-10T20:32:00-04:00',
                endTime: '2025-06-11T00:00:00-04:00',
                continuesAfter: true,
                metadata: {
                  fullStart: '2025-06-10T20:32:00-04:00',
                  fullEnd: '2025-06-11T04:26:00-04:00',
                },
              }),
            ],
            series: [],
          }),
        ],
      });
      const morning = makeTimeline({
        date: '2025-06-11',
        dayStart: '2025-06-11T00:00:00-04:00',
        dayEnd: '2025-06-12T00:00:00-04:00',
        lanes: [
          makeLane({
            id: 'sleep',
            phenotype: 'sleep',
            label: 'Sleep',
            accent: 'orange',
            events: [
              makeEvent({
                id: 'sleep_morning',
                label: 'Main sleep',
                category: 'main_sleep',
                startTime: '2025-06-11T00:00:00-04:00',
                endTime: '2025-06-11T04:26:00-04:00',
                continuesBefore: true,
                metadata: {
                  fullStart: '2025-06-10T20:32:00-04:00',
                  fullEnd: '2025-06-11T04:26:00-04:00',
                },
              }),
            ],
            series: [],
          }),
        ],
      });
      return [
        { date: '2025-06-10', timeline: evening, status: 'loaded' as const, stored: true },
        { date: '2025-06-11', timeline: morning, status: 'loaded' as const, stored: true },
      ];
    };

    const renderNight = () =>
      render(
        <CollapsedTimeline
          days={nightAcrossMidnight()}
          focusDate="2025-06-11"
          hidden={new Set()}
          onTogglePhenotype={vi.fn()}
          selectedKey={null}
          onSelect={vi.fn()}
          zoom={1}
          onLoadDay={vi.fn()}
        />,
      );

    const bar = (panelDate: string) =>
      screen.getByTestId(`collapsed-day-${panelDate}`).querySelector('rect[rx]') as SVGRectElement;

    it('runs each half to its panel edge so the two meet', () => {
      renderNight();
      const evening = bar('2025-06-10');
      const morning = bar('2025-06-11');
      const panelWidth = Number(
        screen
          .getByTestId('collapsed-day-2025-06-10')
          .querySelector('svg')
          ?.getAttribute('width'),
      );

      // The evening half reaches the right edge, the morning half starts at the
      // left edge. The axis inset would otherwise leave a gap at the join.
      const eveningEnd = Number(evening.getAttribute('x')) + Number(evening.getAttribute('width'));
      expect(eveningEnd).toBeCloseTo(panelWidth, 0);
      expect(Number(morning.getAttribute('x'))).toBe(0);
    });

    it('squares off the cut ends rather than rounding them', () => {
      renderNight();
      expect(bar('2025-06-10').getAttribute('rx')).toBe('0');
      expect(bar('2025-06-11').getAttribute('rx')).toBe('0');
    });

    it('announces the night once, on the day it began', () => {
      renderNight();
      // Two bars, but only one labelled node: the continuation carries no node.
      expect(screen.getAllByText('Main sleep')).toHaveLength(1);
    });

    it('labels it with the real span, not the half cut off at midnight', () => {
      const { container } = renderNight();
      expect(screen.getByText('8:32 PM – 4:26 AM')).toBeInTheDocument();

      // No drawn label may show the clipped midnight boundary as an end time.
      // (The hover tooltip still reports this day's slice, and says so.)
      const drawn = [...container.querySelectorAll('svg text')].map((node) => node.textContent);
      expect(drawn.some((text) => text?.includes('12:00 AM'))).toBe(false);
    });

    it('still announces a continuation when no earlier panel exists', () => {
      // Scrolled to the very start of the window, the opening half is not
      // rendered at all, so suppressing the label would lose the event.
      render(
        <CollapsedTimeline
          days={nightAcrossMidnight().slice(1)}
          focusDate="2025-06-11"
          hidden={new Set()}
          onTogglePhenotype={vi.fn()}
          selectedKey={null}
          onSelect={vi.fn()}
          zoom={1}
          onLoadDay={vi.fn()}
        />,
      );
      expect(screen.getByText('Main sleep')).toBeInTheDocument();
    });
  });

  it('shows one panel per day so day boundaries stay explicit', () => {
    const timeline = makeTimeline();
    render(
      <CollapsedTimeline
        days={[{ date: '2026-07-01', timeline: null, status: 'unfetched', stored: false }, ...asRange(timeline)]}
        focusDate={timeline.date}
        hidden={new Set()}
        onTogglePhenotype={vi.fn()}
        selectedKey={null}
        onSelect={vi.fn()}
        zoom={1}
        onLoadDay={vi.fn()}
      />,
    );
    expect(screen.getByTestId('collapsed-day-2026-07-01')).toBeInTheDocument();
    expect(screen.getByTestId(`collapsed-day-${timeline.date}`)).toBeInTheDocument();
  });
});

describe('details panel', () => {
  const selection: Selection = { kind: 'event', laneId: 'activity', event: makeEvent() };

  it('shows time, provenance and origin', () => {
    render(
      <DetailsPanel
        selection={selection}
        accent="green"
        timeZone="America/New_York"
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Morning workout');
    expect(screen.getAllByText('7:15 AM – 8:00 AM').length).toBeGreaterThan(0);
    expect(screen.getAllByText('45 min').length).toBeGreaterThan(0);
    expect(screen.getByText('Measured directly')).toBeInTheDocument();
    expect(screen.getByText('activity.workout_session')).toBeInTheDocument();
    expect(screen.getByText('1.1.0')).toBeInTheDocument();
  });

  it('can be closed', async () => {
    const onClose = vi.fn();
    render(
      <DetailsPanel
        selection={selection}
        accent="green"
        timeZone="America/New_York"
        onClose={onClose}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Close details' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('explains a clipped interval instead of hiding it', () => {
    const sleep: Selection = {
      kind: 'event',
      laneId: 'sleep',
      event: makeEvent({
        label: 'Main sleep',
        continuesBefore: true,
        metadata: {
          durationMinutes: 470,
          fullStart: '2025-06-09T23:10:00-04:00',
          fullEnd: '2025-06-10T07:00:00-04:00',
        },
      }),
    };
    render(
      <DetailsPanel
        selection={sleep}
        accent="orange"
        timeZone="America/New_York"
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText(/Starts on the previous day/)).toBeInTheDocument();
    // The full, unclipped times are what is displayed.
    expect(screen.getByText('11:10 PM – 7:00 AM')).toBeInTheDocument();
  });

  it('describes a selected sample on a continuous line', () => {
    const point: Selection = {
      kind: 'series-point',
      laneId: 'heart_rate',
      series: makeSeries(),
      point: { timestamp: '2025-06-10T12:00:00-04:00', value: 88 },
    };
    render(
      <DetailsPanel
        selection={point}
        accent="blue"
        timeZone="America/New_York"
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Heart rate');
    expect(screen.getByText('88 bpm')).toBeInTheDocument();
    expect(screen.getByText('Measured directly')).toBeInTheDocument();
  });
});

describe('controls', () => {
  function renderControls(overrides: Partial<Parameters<typeof TimelineControls>[0]> = {}) {
    const props = {
      lanes: makeTimeline().lanes,
      hidden: new Set<string>(),
      onToggleLane: vi.fn(),
      mode: 'expanded' as const,
      onModeChange: vi.fn(),
      zoom: 1,
      onZoomChange: vi.fn(),
      onRefresh: vi.fn(),
      refreshing: false,
      ...overrides,
    };
    render(<TimelineControls {...props} />);
    return props;
  }

  it('switches between expanded and collapsed', async () => {
    const props = renderControls();
    await userEvent.click(screen.getByTestId('mode-collapsed'));
    expect(props.onModeChange).toHaveBeenCalledWith('collapsed');
  });

  it('offers a DAG tab alongside expanded and collapsed', async () => {
    const props = renderControls();
    const tabs = screen.getByRole('group', { name: 'Timeline detail' });
    expect(within(tabs).getAllByRole('button')).toHaveLength(3);
    expect(screen.getByTestId('mode-dag')).toHaveTextContent('DAG');

    await userEvent.click(screen.getByTestId('mode-dag'));
    expect(props.onModeChange).toHaveBeenCalledWith('dag');
  });

  it('hides zoom on the DAG, where it means nothing', () => {
    renderControls({ mode: 'dag' });
    expect(screen.queryByRole('button', { name: 'Zoom in' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('stream-visibility-toggle')).not.toBeInTheDocument();
  });

  it('lists available streams and explains the unavailable ones', async () => {
    renderControls();
    await userEvent.click(screen.getByTestId('stream-visibility-toggle'));
    const popover = screen.getByTestId('stream-visibility-popover');
    expect(within(popover).getByText('Activity')).toBeInTheDocument();
    expect(within(popover).getByText('No data yesterday')).toBeInTheDocument();
    expect(
      within(popover).getByText(/No HRV data was available yesterday/),
    ).toBeInTheDocument();
  });

  it('toggles a lane', async () => {
    const props = renderControls();
    await userEvent.click(screen.getByTestId('stream-visibility-toggle'));
    const boxes = within(screen.getByTestId('stream-visibility-popover')).getAllByRole('checkbox');
    await userEvent.click(boxes[0]);
    expect(props.onToggleLane).toHaveBeenCalled();
  });

  it('refreshes', async () => {
    const props = renderControls();
    await userEvent.click(screen.getByTestId('refresh-button'));
    expect(props.onRefresh).toHaveBeenCalled();
  });

  it('disables zoom-out at the minimum', () => {
    renderControls({ zoom: 1 });
    expect(screen.getByRole('button', { name: 'Zoom out' })).toBeDisabled();
  });
});

describe('page chrome', () => {
  it('shows Yesterday as the only navigation item', () => {
    render(<Sidebar sources={null} lastSync={null} {...DAY_PROPS} />);
    const nav = screen.getByRole('navigation', { name: 'Main navigation' });
    // One item, which now also acts as "jump back to yesterday".
    expect(within(nav).getAllByRole('button')).toHaveLength(1);
    expect(within(nav).getByText('Yesterday')).toBeInTheDocument();
    for (const forbidden of ['Home', 'Trends', 'Insights', 'Settings']) {
      expect(within(nav).queryByText(forbidden)).not.toBeInTheDocument();
    }
  });

  it('lets a day be picked from the calendar', async () => {
    const onSelectDate = vi.fn();
    render(
      <Sidebar
        sources={null}
        lastSync={null}
        {...DAY_PROPS}
        dayIndex={
          new Map([
            [
              '2025-06-05',
              {
                date: '2025-06-05',
                isToday: false,
                isYesterday: false,
                stored: true,
                eventCount: 12,
                coverage: 0.9,
                hasData: true,
              },
            ],
          ])
        }
        onSelectDate={onSelectDate}
      />,
    );

    expect(screen.getByTestId('calendar-grid')).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('calendar-day-2025-06-05'));
    expect(onSelectDate).toHaveBeenCalledWith('2025-06-05');
  });

  it('never offers a future day', () => {
    render(<Sidebar sources={null} lastSync={null} {...DAY_PROPS} />);
    // DAY_PROPS puts "today" at 2025-06-11, so the 12th must be unselectable.
    expect(screen.getByTestId('calendar-day-2025-06-12')).toBeDisabled();
    expect(screen.getByTestId('calendar-day-2025-06-10')).toBeEnabled();
  });

  it('titles the page by the day being shown', () => {
    const { rerender } = render(
      <PageHeader timeline={null} selectedDate="2025-06-10" yesterday="2025-06-10" today="2025-06-11" />,
    );
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Yesterday');

    rerender(
      <PageHeader timeline={null} selectedDate="2025-06-04" yesterday="2025-06-10" today="2025-06-11" />,
    );
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Wednesday, June 4, 2025');

    rerender(
      <PageHeader timeline={null} selectedDate="2025-06-11" yesterday="2025-06-10" today="2025-06-11" />,
    );
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Today');
    expect(screen.getByText('In progress')).toBeInTheDocument();
  });

  it('names the MCP server behind each source', () => {
    render(
      <Sidebar
        sources={{
          mockData: false,
          checkedAt: null,
          sources: [
            {
              id: 'home_assistant',
              name: 'Home Assistant',
              status: 'connected',
              mcpServer: 'ha-mcp',
              transport: 'rest',
              capabilities: [],
              detail: null,
              hasData: true,
            },
            {
              id: 'garmin',
              name: 'Garmin',
              status: 'connected',
              mcpServer: 'garmin',
              transport: 'mcp',
              capabilities: ['sleep'],
              detail: null,
              hasData: false,
            },
          ],
        }}
        lastSync={null}
        {...DAY_PROPS}
      />,
    );
    expect(screen.getByText('ha-mcp')).toBeInTheDocument();
    expect(screen.getByText('garmin')).toBeInTheDocument();
    expect(screen.getByText('read over MCP')).toBeInTheDocument();

    // "Wearables" is an internal abstraction, not an MCP integration.
    expect(screen.queryByText('Wearables')).not.toBeInTheDocument();

    // A source that answered but had nothing says so rather than looking broken.
    expect(screen.getByText(/no data yesterday/)).toBeInTheDocument();
  });

  it('renders each source with a status label, not colour alone', () => {
    render(
      <Sidebar
        sources={{
          mockData: true,
          checkedAt: null,
          sources: [
            {
              id: 'home_assistant',
              name: 'Home Assistant',
              status: 'mock_data',
              mcpServer: 'ha-mcp',
              transport: 'mock',
              capabilities: [],
              detail: 'Generated locally',
              hasData: true,
            },
            {
              id: 'garmin',
              name: 'Garmin',
              status: 'error',
              mcpServer: 'garmin',
              transport: 'mcp',
              capabilities: [],
              detail: 'The provider failed',
              hasData: false,
            },
          ],
        }}
        lastSync={null}
        {...DAY_PROPS}
      />,
    );
    expect(screen.getByText('Mock data')).toBeInTheDocument();
    expect(screen.getByText('Error')).toBeInTheDocument();
    // A failing source still explains itself; a healthy one does not.
    expect(screen.getByText('The provider failed')).toBeInTheDocument();
    expect(screen.queryByText('Generated locally')).not.toBeInTheDocument();
  });

  it('reports facts in the status card and never praise', () => {
    render(<PageHeader timeline={makeTimeline()} {...DAY_PROPS} />);
    expect(screen.getByText('Day successfully reconstructed')).toBeInTheDocument();
    expect(screen.getByText('Data available from 2 sources')).toBeInTheDocument();
    expect(screen.getByText(/93% coverage/)).toBeInTheDocument();
    for (const praise of ['Great job', 'You had a good day', 'Excellent', 'Poor sleep']) {
      expect(screen.queryByText(praise)).not.toBeInTheDocument();
    }
  });

  it('states the fixed date range with no picker', () => {
    render(<PageHeader timeline={makeTimeline()} {...DAY_PROPS} />);
    expect(
      screen.getByText(/Your data from yesterday, 12:00 AM to 11:59 PM/),
    ).toBeInTheDocument();
    expect(document.querySelector('input[type="date"]')).toBeNull();
  });

  it('surfaces source errors and warnings separately', () => {
    render(
      <SourceNotices
        warnings={['sensor.bedroom_temperature returned no history.']}
        errors={['Home Assistant could not be reached at the configured URL.']}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Home Assistant could not be reached');
    expect(screen.getByText(/returned no history/)).toBeInTheDocument();
  });

  it('no longer shows the observed-timing narrative', () => {
    // Removed at the owner's request; the timeline itself carries the timing.
    const timeline = makeTimeline();
    render(<PageHeader timeline={timeline} {...DAY_PROPS} />);
    expect(screen.queryByText('Observed timing')).not.toBeInTheDocument();
    for (const line of timeline.highlights) {
      expect(screen.queryByText(line)).not.toBeInTheDocument();
    }
  });

  it('shows a skeleton while loading', () => {
    render(<TimelineSkeleton />);
    expect(screen.getByTestId('timeline-skeleton')).toHaveAttribute('aria-busy', 'true');
  });
});
