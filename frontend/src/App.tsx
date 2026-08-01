import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from './api/client';
import { DetailsPanel } from './details/DetailsPanel';
import { PageHeader } from './components/PageHeader';
import { Sidebar } from './components/Sidebar';
import { ErrorState, SourceNotices, TimelineSkeleton } from './components/States';
import { TimelineControls, isViewMode, type ViewMode } from './components/TimelineControls';
import { useDataSources } from './hooks/useDataSources';
import { datesAround, useDayRange } from './hooks/useDayRange';
import { isStringArray, usePersistentState } from './hooks/usePersistentState';
import { applyLaneOrder, moveLaneBefore } from './utilities/laneOrder';
import { useDays } from './hooks/useDays';
import { useTimeline } from './hooks/useTimeline';
import { DagView } from './dag/DagView';
import { CollapsedTimeline } from './timeline/CollapsedTimeline';
import { Timeline } from './timeline/Timeline';
import type { Lane, Selection } from './types/timeline';
import { selectionKey } from './types/timeline';

export function App() {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const { timeline, state, error, refreshing, refresh, reload } = useTimeline(selectedDate);
  const { index: dayIndex, today, yesterday } = useDays(timeline?.generatedAt);
  const { report: sources, state: sourcesState } = useDataSources(timeline?.generatedAt);

  // The page opens on the day in progress. The backend decides which day that
  // is, using the configured timezone — waiting for it avoids the browser
  // picking a different day from the server across midnight or a DST change.
  //
  // Today is incomplete by definition, and the header says so rather than
  // presenting a part-day as a finished one. A day still running is served
  // from cache and never re-fetched by the poll, so opening the page does not
  // spawn an MCP subprocess every minute; Refresh is how you ask for the
  // hours since the last sync.
  useEffect(() => {
    if (selectedDate === null && today) setSelectedDate(today);
  }, [selectedDate, today]);
  // Which tab you were on is part of the same arrangement as the row order and
  // what you hid: coming back to Expanded after every reload undoes a choice
  // you made on purpose.
  const [mode, setMode] = usePersistentState<ViewMode>('view-mode', 'expanded', isViewMode);
  /**
   * Rows hidden from the expanded timeline.
   *
   * Persisted for the same reason the row order is: it is an arrangement of
   * your own view, not something derived from the data, and a view that forgot
   * it on every reload — or in the next tab — would make the control not worth
   * using. Stored as lane ids, so a lane that disappears on a day with no data
   * for it comes back still hidden, and one you have never hidden is visible.
   */
  const [hiddenIds, setHiddenIds] = usePersistentState<string[]>(
    'hidden-lanes',
    [],
    isStringArray,
  );
  const hidden = useMemo(() => new Set(hiddenIds), [hiddenIds]);
  const [zoom, setZoom] = useState(1);
  const [selection, setSelection] = useState<Selection | null>(null);
  // Row order is the user's own arrangement of their view, so it outlives the
  // page rather than resetting on every reload.
  const [laneOrder, setLaneOrder] = usePersistentState<string[]>(
    'lane-order',
    [],
    isStringArray,
  );
  /**
   * Which lanes the collapsed view draws. Two lists rather than one, because
   * "not in the shown list" has to mean two different things: a lane switched
   * off, and a lane whose default is off because it carries no major events.
   * Storing only the off list would turn every newly connected source on.
   */
  const [collapsedHiddenIds, setCollapsedHiddenIds] = usePersistentState<string[]>(
    'collapsed-hidden',
    [],
    isStringArray,
  );
  const [collapsedShownIds, setCollapsedShownIds] = usePersistentState<string[]>(
    'collapsed-shown',
    [],
    isStringArray,
  );
  // Off by default: the collapsed line is meant to be readable at a glance.
  const [collapsedAllEvents, setCollapsedAllEvents] = usePersistentState<boolean>(
    'collapsed-all-events',
    false,
    (value): value is boolean => typeof value === 'boolean',
  );
  const collapsedHidden = useMemo(() => new Set(collapsedHiddenIds), [collapsedHiddenIds]);
  const collapsedShown = useMemo(() => new Set(collapsedShownIds), [collapsedShownIds]);
  const toggleCollapsedPhenotype = useCallback(
    (laneId: string, on: boolean) => {
      // Every toggle is recorded explicitly, so the choice survives a lane's
      // default changing when a day with different data is loaded.
      setCollapsedShownIds((current) =>
        on ? [...new Set([...current, laneId])] : current.filter((id) => id !== laneId),
      );
      setCollapsedHiddenIds((current) =>
        on ? current.filter((id) => id !== laneId) : [...new Set([...current, laneId])],
      );
    },
    [setCollapsedHiddenIds, setCollapsedShownIds],
  );

  /**
   * The collapsed view spans a month either side of the chosen day. It is
   * clamped at today because a day that has not happened holds no data and
   * cannot be reconstructed. Panels load as they scroll into view rather than
   * all at once; see useDayRange.
   */
  const rangeDates = useMemo(
    () => (selectedDate ? datesAround(selectedDate, 30, 30, today) : []),
    [selectedDate, today],
  );
  const storedDates = useMemo(() => {
    const stored = new Set<string>();
    for (const [date, day] of dayIndex) {
      if (day.stored) stored.add(date);
    }
    return stored;
  }, [dayIndex]);
  const { days: rangeDays, load: loadDay } = useDayRange(rangeDates, storedDates);

  // A timeline for a day the user has navigated away from is stale: showing it
  // under the new heading would attribute one day's data to another.
  const current = timeline && timeline.date === selectedDate ? timeline : null;
  const allLanes: Lane[] = current?.lanes ?? [];
  // Lanes with no data are never shown as empty rows.
  const unordered = useMemo(() => allLanes.filter((lane) => lane.available), [allLanes]);

  /**
   * Apply the user's row order. It is stored as a list of lane ids, which may
   * be stale in both directions: a lane can vanish when a day has no data for
   * it, and a new one can appear. Known lanes keep their saved position and
   * anything unrecognised falls to the bottom in its original order, so a lane
   * that comes back tomorrow is where it was left.
   */
  const availableLanes = useMemo(
    () => applyLaneOrder(unordered, laneOrder),
    [unordered, laneOrder],
  );

  const visibleLanes = useMemo(
    () => availableLanes.filter((lane) => !hidden.has(lane.id)),
    [availableLanes, hidden],
  );

  /**
   * Exactly the rows the Expanded tab is drawing, in that order.
   *
   * The DAG tab takes its rows from this and nothing else, so the two tabs
   * cannot disagree about which streams this day has: hide a row and its
   * variables leave the graph, and a lane with no data today never reaches it
   * to begin with.
   */
  const timelineLanes = useMemo(
    () =>
      visibleLanes.map(({ id, label, description, accent }) => ({
        id,
        label,
        description,
        accent,
      })),
    [visibleLanes],
  );

  /** Move one lane to where another currently sits, and remember it. */
  const reorderLanes = useCallback(
    (laneId: string, beforeLaneId: string) => {
      setLaneOrder(
        moveLaneBefore(
          availableLanes.map((lane) => lane.id),
          laneOrder,
          laneId,
          beforeLaneId,
        ),
      );
    },
    [availableLanes, laneOrder, setLaneOrder],
  );

  // A selected event belongs to the day it was found on, so changing day
  // clears it rather than carrying it across.
  useEffect(() => {
    setSelection(null);
  }, [selectedDate]);

  /**
   * Keep the selected mark across refreshes by re-resolving it from the new
   * payload, so a background sync does not close the details panel.
   */
  useEffect(() => {
    if (!current || !selection) return;
    // A mark picked in the collapsed view can belong to any day in the window.
    // Re-resolving it against the day on screen would fail to find it and shut
    // the panel, which is why clicking anything but the focused day's marks
    // used to do nothing at all.
    if (selection.kind === 'event' && selection.date && selection.date !== current.date) return;
    if (selection.kind === 'event') {
      const lane = current.lanes.find((item) => item.id === selection.laneId);
      const event = lane?.events.find((item) => item.id === selection.event.id);
      if (!event) {
        setSelection(null);
      } else if (event !== selection.event) {
        setSelection({ kind: 'event', laneId: selection.laneId, event });
      }
      return;
    }
    const lane = current.lanes.find((item) => item.id === selection.laneId);
    const series = lane?.series.find((item) => item.id === selection.series.id);
    const point = series?.points.find((item) => item.timestamp === selection.point.timestamp);
    if (!series || !point) {
      setSelection(null);
    } else if (series !== selection.series) {
      setSelection({ kind: 'series-point', laneId: selection.laneId, series, point });
    }
  }, [current, selection]);

  /** Rows the user added are stored server-side, so removal is a request. */
  const deleteRow = useCallback(
    (laneId: string) => {
      void api
        .deleteRow(laneId)
        .then(() => reload())
        .catch(() => reload());
    },
    [reload],
  );

  const toggleLane = useCallback(
    (laneId: string) => {
      setHiddenIds((current) =>
        current.includes(laneId)
          ? current.filter((id) => id !== laneId)
          : [...current, laneId],
      );
    },
    [setHiddenIds],
  );

  const selectedKey = selection ? selectionKey(selection) : null;
  const accent =
    (selection && allLanes.find((lane) => lane.id === selection.laneId)?.accent) ?? 'blue';
  const lastSync = current?.summary.completedAt ?? null;

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900">
      <Sidebar
        sources={sources}
        state={sourcesState}
        lastSync={lastSync}
        selectedDate={selectedDate}
        today={today}
        dayIndex={dayIndex}
        onSelectDate={setSelectedDate}
        loadingDay={state === 'loading'}
        onSourcesChanged={() => void refresh()}
      />

      <main className="flex min-w-0 flex-1 flex-col" id="timeline">
        <PageHeader
          timeline={current}
          selectedDate={selectedDate}
          yesterday={yesterday}
          today={today}
        />

        {/*
          Only genuine failures are surfaced here. Per-entity warnings (an
          entity with no recorder history, say) are kept in the payload and the
          MCP tools, but a banner on every load turns a working setup into a
          page that always looks broken.
        */}
        {current?.summary.errors.length ? (
          <SourceNotices warnings={[]} errors={current.summary.errors} />
        ) : null}

        <div className="flex min-h-0 flex-1 flex-col px-8 pb-8 lg:flex-row lg:gap-5">
          <section
            className="min-w-0 flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-white"
            aria-label="Day timeline"
          >
            {state === 'error' && error ? (
              <ErrorState error={error} onRetry={reload} />
            ) : null}

            {state === 'loading' && !current ? <TimelineSkeleton /> : null}

            {current ? (
              <>
                <TimelineControls
                  lanes={allLanes}
                  hidden={hidden}
                  onToggleLane={toggleLane}
                  mode={mode}
                  onModeChange={setMode}
                  zoom={zoom}
                  onZoomChange={setZoom}
                  onRefresh={() => void refresh()}
                  refreshing={refreshing}
                />

                {mode === 'dag' ? (
                  <DagView date={selectedDate} lanes={timelineLanes} />
                ) : visibleLanes.length === 0 ? (
                  <p className="px-5 py-10 text-center text-[13px] text-slate-500">
                    {availableLanes.length === 0
                      ? 'No data source returned usable data for this day. Check the Data Sources panel.'
                      : 'Every available data stream is hidden. Re-enable one from “Visible data streams”.'}
                  </p>
                ) : mode === 'expanded' ? (
                  <Timeline
                    timeline={current}
                    lanes={visibleLanes}
                    selectedKey={selectedKey}
                    onSelect={setSelection}
                    zoom={zoom}
                    onReorder={reorderLanes}
                    onHideLane={toggleLane}
                    onDeleteLane={deleteRow}
                    date={selectedDate}
                    onRowAdded={reload}
                  />
                ) : (
                  <CollapsedTimeline
                    days={rangeDays}
                    focusDate={selectedDate}
                    hidden={collapsedHidden}
                    excluded={hidden}
                    shown={collapsedShown}
                    onTogglePhenotype={toggleCollapsedPhenotype}
                    allEvents={collapsedAllEvents}
                    onToggleAllEvents={() => setCollapsedAllEvents((value) => !value)}
                    selectedKey={selectedKey}
                    onSelect={setSelection}
                    zoom={zoom}
                    onLoadDay={loadDay}
                  />
                )}


                <p className="border-t border-slate-100 px-5 py-3 text-[11.5px] text-slate-400">
                  {current.mockData
                    ? 'Showing locally generated mock data. No wearable account or Home Assistant instance is connected.'
                    : `${current.date} · data synced from ${current.summary.sourcesChecked.join(' and ')}. ${current.summary.rawRecordCount.toLocaleString('en-US')} raw records processed locally.`}
                </p>
              </>
            ) : null}
          </section>

          {selection ? (
            <DetailsPanel
              selection={selection}
              accent={accent}
              timeZone={current?.localTimezone ?? 'UTC'}
              displayedDate={selectedDate}
              onClose={() => setSelection(null)}
            />
          ) : null}
        </div>
      </main>
    </div>
  );
}
