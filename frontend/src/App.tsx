import { useCallback, useEffect, useMemo, useState } from 'react';
import { DetailsPanel } from './details/DetailsPanel';
import { PageHeader } from './components/PageHeader';
import { Sidebar } from './components/Sidebar';
import { ErrorState, SourceNotices, TimelineSkeleton } from './components/States';
import { TimelineControls, type ViewMode } from './components/TimelineControls';
import { useDataSources } from './hooks/useDataSources';
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

  // The backend decides which day "yesterday" is, using the configured
  // timezone. Waiting for it avoids the browser picking a different day.
  useEffect(() => {
    if (selectedDate === null && yesterday) setSelectedDate(yesterday);
  }, [selectedDate, yesterday]);
  const [mode, setMode] = useState<ViewMode>('expanded');
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [zoom, setZoom] = useState(1);
  const [selection, setSelection] = useState<Selection | null>(null);

  // A timeline for a day the user has navigated away from is stale: showing it
  // under the new heading would attribute one day's data to another.
  const current = timeline && timeline.date === selectedDate ? timeline : null;
  const allLanes: Lane[] = current?.lanes ?? [];
  // Lanes with no data are never shown as empty rows.
  const availableLanes = useMemo(() => allLanes.filter((lane) => lane.available), [allLanes]);
  const visibleLanes = useMemo(
    () => availableLanes.filter((lane) => !hidden.has(lane.id)),
    [availableLanes, hidden],
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

  const toggleLane = useCallback((laneId: string) => {
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(laneId)) next.delete(laneId);
      else next.add(laneId);
      return next;
    });
  }, []);

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
        yesterday={yesterday}
        today={today}
        dayIndex={dayIndex}
        onSelectDate={setSelectedDate}
        loadingDay={state === 'loading'}
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
            aria-label="Yesterday timeline"
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
                  <DagView date={selectedDate} />
                ) : visibleLanes.length === 0 ? (
                  <p className="px-5 py-10 text-center text-[13px] text-slate-500">
                    {availableLanes.length === 0
                      ? 'No data source returned usable data for yesterday. Check the Data Sources panel.'
                      : 'Every available data stream is hidden. Re-enable one from “Visible data streams”.'}
                  </p>
                ) : mode === 'expanded' ? (
                  <Timeline
                    timeline={current}
                    lanes={visibleLanes}
                    selectedKey={selectedKey}
                    onSelect={setSelection}
                    zoom={zoom}
                  />
                ) : (
                  <CollapsedTimeline
                    timeline={current}
                    lanes={availableLanes}
                    selectedKey={selectedKey}
                    onSelect={setSelection}
                    zoom={zoom}
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
              onClose={() => setSelection(null)}
            />
          ) : null}
        </div>
      </main>
    </div>
  );
}
