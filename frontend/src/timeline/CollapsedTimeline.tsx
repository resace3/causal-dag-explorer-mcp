/**
 * Collapsed mode: one chronological line answering "what were the major
 * observable events?".
 *
 * No causal arrows, no delayed-effect edges, no connections between events —
 * only the events themselves on a shared time axis.
 *
 * Several days can be shown at once, and each gets its own panel with its own
 * scale rather than being laid on one continuous ruler. That is deliberate: a
 * day is 23 or 25 hours across a daylight-saving change, so a single linear
 * ruler would either misplace the boundaries or silently stretch one day. Panel
 * per day keeps every day internally exact and makes the boundary explicit.
 */

import { useEffect, useMemo, useRef } from 'react';
import { LaneIcon } from '../components/Icons';
import { useElementWidth } from '../hooks/useElementWidth';
import type { RangeDay } from '../hooks/useDayRange';
import { Mark, approximateTextWidth, describeEvent, eventTooltip } from '../lanes/shared';
import type { DayTimeline, Lane, Selection, TimelineEvent } from '../types/timeline';
import { AXIS_HEIGHT, LANE_LABEL_WIDTH, MAJOR_CATEGORIES, accentTheme } from '../utilities/lanes';
import { formatIsoDate, formatTimeRange } from '../utilities/time';
import { AxisRow, GridLines } from './Axis';
import { createScale } from './scale';

const HEIGHT = 250;
const BASELINE = 132;
const MIN_DAY_WIDTH = 520;

/**
 * Half the width of a mark's caption, for its hit area.
 *
 * Floored so that a one-word label still gets a target worth aiming at, and
 * measured from the label alone: the time range under it is narrower, so the
 * wider of the two is what the block occupies.
 */
function labelHalfWidth(label: string): number {
  return Math.max(approximateTextWidth(label, 11.5), 56) / 2;
}

export interface MajorEvent {
  event: TimelineEvent;
  lane: Lane;
}

/** Selects the events a person would list if asked what happened that day. */
export function majorEvents(lanes: Lane[], hidden: Set<string> = new Set()): MajorEvent[] {
  const chosen: MajorEvent[] = [];
  for (const lane of lanes) {
    if (!lane.available || hidden.has(lane.id)) continue;
    for (const event of lane.events) {
      if (!event.category || !MAJOR_CATEGORIES.has(event.category)) continue;
      // One elevated-heart-rate marker per lane is enough at this zoom level.
      if (event.category === 'elevated' && chosen.some((item) => item.event.category === 'elevated')) {
        continue;
      }
      chosen.push({ event, lane });
    }
  }
  return chosen.sort(
    (a, b) => new Date(a.event.startTime).getTime() - new Date(b.event.startTime).getTime(),
  );
}

/** True when a lane has anything in the curated major-event list. */
export function definesMajorEvents(lane: Lane): boolean {
  return lane.events.some((event) => event.category && MAJOR_CATEGORIES.has(event.category));
}

/**
 * Lanes that carry a major event *anywhere in the window*.
 *
 * Deliberately not per-day. Whether a lane is curated down to its major events
 * decides both its default and what it draws, and answering that from whichever
 * day happened to load first makes Presence & Motion appear on Tuesday and
 * vanish on Wednesday — the same lane behaving two ways for no reason the
 * reader can see.
 */
export function majorLaneIds(days: RangeDay[]): Set<string> {
  const ids = new Set<string>();
  for (const day of days) {
    for (const lane of day.timeline?.lanes ?? []) {
      if (lane.available && definesMajorEvents(lane)) ids.add(lane.id);
    }
  }
  return ids;
}

/**
 * What the collapsed line actually draws.
 *
 * Two rules, because "major" is a curated list of categories and not every lane
 * has one:
 *
 *  * A lane that defines major events contributes those.
 *  * A lane that defines none contributes everything it recorded — otherwise
 *    switching it on would do nothing at all, and some lanes (computer use,
 *    environment, HRV) could never be shown here.
 *
 * `allEvents` drops the curation entirely, so anything on the Expanded tab can
 * be brought onto this one.
 */
export function collapsedEvents(
  lanes: Lane[],
  visible: Set<string>,
  curatedLanes: Set<string> = new Set(),
  allEvents = false,
): MajorEvent[] {
  const chosen: MajorEvent[] = [];
  for (const lane of lanes) {
    if (!lane.available || !visible.has(lane.id)) continue;
    const curated = !allEvents && curatedLanes.has(lane.id);
    for (const event of lane.events) {
      if (curated) {
        if (!event.category || !MAJOR_CATEGORIES.has(event.category)) continue;
        if (
          event.category === 'elevated' &&
          chosen.some((item) => item.event.category === 'elevated')
        ) {
          continue;
        }
      }
      chosen.push({ event, lane });
    }
  }
  return chosen.sort(
    (a, b) => new Date(a.event.startTime).getTime() - new Date(b.event.startTime).getTime(),
  );
}

/**
 * Every lane with events anywhere in the window, so nothing on the Expanded tab
 * is missing from this list. Earlier this offered only lanes with a *major*
 * event, which meant a lane like Computer Use could not be shown here at all.
 *
 * Events, not lanes: a lane holding only a continuous series — a heart-rate
 * trace with no discrete readings — has nothing this view can draw. One line of
 * marks cannot carry a curve, and picking a moment out of one to stand for it
 * would be inventing salience, which is the same reason the DAG tab refuses to
 * give a continuous signal a node. Such a lane is left out rather than offered
 * as a switch that does nothing.
 */
export function togglablePhenotypes(days: RangeDay[], excluded: Set<string> = new Set()): Lane[] {
  const seen = new Map<string, Lane>();
  for (const day of days) {
    for (const lane of day.timeline?.lanes ?? []) {
      if (!lane.available || !lane.events.length) continue;
      // Removed from the Expanded tab means removed, not "removed over there".
      // A switch here for a row the user took off their timeline would offer
      // to bring back something they have already said they do not want.
      if (excluded.has(lane.id)) continue;
      if (!seen.has(lane.id)) seen.set(lane.id, lane);
    }
  }
  return [...seen.values()];
}

/**
 * Which lanes the collapsed line shows: the ones that carry the day's major
 * events, plus or minus what the user has said explicitly.
 *
 * A lane with no major events starts off rather than on, so switching a new
 * source on does not quietly triple the number of marks on a line whose whole
 * point is that it is short.
 */
export function visibleLaneIds(
  lanes: Lane[],
  hidden: Set<string>,
  shown: Set<string>,
  curatedLanes: Set<string> = new Set(),
): Set<string> {
  const visible = new Set<string>();
  for (const lane of lanes) {
    if (shown.has(lane.id)) visible.add(lane.id);
    else if (!hidden.has(lane.id) && curatedLanes.has(lane.id)) visible.add(lane.id);
  }
  return visible;
}

interface CollapsedTimelineProps {
  days: RangeDay[];
  /** The day the window is centred on, scrolled to on arrival. */
  focusDate: string | null;
  /** Lanes switched off explicitly *here*. */
  hidden: Set<string>;
  /** Lanes hidden on the Expanded tab, which are not offered here at all. */
  excluded: Set<string>;
  /** Lanes switched on explicitly, which is how a lane with no major events
   *  gets here at all. */
  shown: Set<string>;
  onTogglePhenotype: (laneId: string, on: boolean) => void;
  /** Drop the major-event curation and draw everything the lanes hold. */
  allEvents: boolean;
  onToggleAllEvents: () => void;
  selectedKey: string | null;
  onSelect: (selection: Selection) => void;
  zoom: number;
  onLoadDay: (date: string) => void;
}

export function CollapsedTimeline({
  days,
  focusDate,
  hidden,
  excluded,
  shown,
  onTogglePhenotype,
  allEvents,
  onToggleAllEvents,
  selectedKey,
  onSelect,
  zoom,
  onLoadDay,
}: CollapsedTimelineProps) {
  const { ref, width } = useElementWidth<HTMLDivElement>(900);
  const scroller = useRef<HTMLDivElement | null>(null);
  const dayWidth = Math.max(MIN_DAY_WIDTH, width / Math.max(1, days.length)) * zoom;
  const focusIndex = days.findIndex((day) => day.date === focusDate);
  const centred = useRef<string | null>(null);

  /**
   * Put the chosen day in the middle, with history to its left and what came
   * after to its right. Only on arrival or when the day changes — re-centring
   * as panels load would yank the view out from under someone scrolling.
   */
  useEffect(() => {
    const node = scroller.current;
    if (!node || focusIndex < 0 || centred.current === focusDate) return;
    node.scrollLeft = Math.max(
      0,
      focusIndex * dayWidth - (node.clientWidth - dayWidth) / 2,
    );
    centred.current = focusDate;
  }, [focusDate, focusIndex, dayWidth]);

  const phenotypes = useMemo(() => togglablePhenotypes(days, excluded), [days, excluded]);
  const curated = useMemo(() => majorLaneIds(days), [days]);
  const visible = useMemo(
    () => visibleLaneIds(phenotypes, hidden, shown, curated),
    [phenotypes, hidden, shown, curated],
  );
  const total = useMemo(
    () =>
      days.reduce(
        (count, day) =>
          count + collapsedEvents(day.timeline?.lanes ?? [], visible, curated, allEvents).length,
        0,
      ),
    [days, visible, curated, allEvents],
  );
  const loaded = days.filter((day) => day.status === 'loaded').length;

  return (
    <div data-testid="timeline-collapsed">
      {phenotypes.length ? (
        <div
          className="flex flex-wrap items-center gap-1.5 border-b border-slate-100 px-5 py-2.5"
          role="group"
          aria-label="Phenotypes shown"
          data-testid="collapsed-phenotypes"
        >
          <span className="mr-1 text-[10.5px] font-semibold uppercase tracking-[0.07em] text-slate-400">
            Show
          </span>
          {phenotypes.map((lane) => {
            const theme = accentTheme(lane.accent);
            const on = visible.has(lane.id);
            return (
              <button
                key={lane.id}
                type="button"
                aria-pressed={on}
                data-testid={`collapsed-toggle-${lane.id}`}
                onClick={() => onTogglePhenotype(lane.id, !on)}
                className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] font-medium transition ${
                  on ? '' : 'opacity-45 grayscale'
                }`}
                style={{
                  borderColor: on ? theme.soft : '#e2e8f0',
                  backgroundColor: on ? theme.band : '#ffffff',
                  color: on ? theme.text : '#94a3b8',
                }}
              >
                <LaneIcon laneId={lane.id} size={13} />
                {lane.label}
              </button>
            );
          })}

          {/* Anything on the Expanded tab can be brought onto this one. It is
              off by default because a line meant to be readable at a glance
              stops being readable with two hundred marks on it. */}
          <button
            type="button"
            aria-pressed={allEvents}
            data-testid="collapsed-all-events"
            onClick={onToggleAllEvents}
            title={
              allEvents
                ? 'Showing every event these lanes recorded'
                : 'Showing each lane’s major events only'
            }
            className={`ml-auto rounded-full border px-2.5 py-1 text-[11.5px] font-medium transition ${
              allEvents
                ? 'border-slate-300 bg-slate-100 text-slate-700'
                : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300 hover:text-slate-700'
            }`}
          >
            {allEvents ? 'Every event' : 'Major events only'}
          </button>
        </div>
      ) : null}

      <div className="flex">
        <div
          className="shrink-0 border-r border-slate-100 bg-white"
          style={{ width: LANE_LABEL_WIDTH }}
        >
          <div style={{ height: AXIS_HEIGHT + DATE_HEADER }} />
          <div className="flex items-center gap-3 px-5" style={{ height: HEIGHT }}>
            <span className="min-w-0">
              <span className="block text-[13.5px] font-semibold leading-tight text-slate-800">
                {allEvents ? 'Every event' : 'Major events'}
              </span>
              <span className="mt-0.5 block text-[11.5px] leading-tight text-slate-500">
                {total} observable event{total === 1 ? '' : 's'}
              </span>
              {days.length > 1 ? (
                // Counting events "across 61 days" would overstate it when only
                // a handful of those days have actually been reconstructed.
                <span className="mt-0.5 block text-[11px] leading-tight text-slate-400">
                  {loaded} of {days.length} days loaded
                </span>
              ) : null}
            </span>
          </div>
          <div style={{ height: AXIS_HEIGHT }} />
        </div>

        <div
          ref={(node) => {
            scroller.current = node;
            ref.current = node;
          }}
          className="min-w-0 flex-1 overflow-x-auto overflow-y-hidden"
          data-testid="collapsed-scroller"
        >
          <div className="flex" style={{ width: dayWidth * days.length }}>
            {days.map((day, index) => (
              <DayStrip
                key={day.date}
                day={day}
                isFirstPanel={index === 0}
                width={dayWidth}
                visible={visible}
                curated={curated}
                allEvents={allEvents}
                selectedKey={selectedKey}
                onSelect={onSelect}
                onLoadDay={onLoadDay}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

const DATE_HEADER = 26;

function DayStrip({
  day,
  width,
  visible,
  curated,
  allEvents,
  selectedKey,
  onSelect,
  onLoadDay,
  isFirstPanel,
}: {
  day: RangeDay;
  width: number;
  isFirstPanel: boolean;
  visible: Set<string>;
  curated: Set<string>;
  allEvents: boolean;
  selectedKey: string | null;
  onSelect: (selection: Selection) => void;
  onLoadDay: (date: string) => void;
}) {
  const timeline = day.timeline;
  const panel = useRef<HTMLDivElement | null>(null);

  /**
   * Fetch a already-processed day when its panel nears the viewport. The window
   * is two months wide, so loading every stored day up front would mean dozens
   * of requests for panels nobody has scrolled to. Days the server has *not*
   * processed are never pulled in this way — that stays a deliberate click.
   */
  const needsLoad = day.stored && day.status === 'unfetched';
  useEffect(() => {
    const node = panel.current;
    if (!node || !needsLoad || typeof IntersectionObserver === 'undefined') return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          onLoadDay(day.date);
          observer.disconnect();
        }
      },
      { root: null, rootMargin: '0px 600px' }, // a panel ahead, so it is ready on arrival
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [needsLoad, day.date, onLoadDay]);

  return (
    <div
      ref={panel}
      className="shrink-0 border-l border-slate-200 first:border-l-0"
      style={{ width }}
      data-testid={`collapsed-day-${day.date}`}
    >
      <div
        className="flex items-center justify-center border-b border-slate-100 bg-slate-50/60 text-[11px] font-semibold text-slate-500"
        style={{ height: DATE_HEADER }}
      >
        {formatIsoDate(day.date)}
      </div>
      {timeline ? (
        <LoadedDay
          timeline={timeline}
          width={width}
          visible={visible}
          curated={curated}
          allEvents={allEvents}
          selectedKey={selectedKey}
          onSelect={onSelect}
          isFirstPanel={isFirstPanel}
        />
      ) : (
        <PlaceholderDay day={day} onLoadDay={onLoadDay} />
      )}
    </div>
  );
}

function PlaceholderDay({
  day,
  onLoadDay,
}: {
  day: RangeDay;
  onLoadDay: (date: string) => void;
}) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-2 px-4 text-center"
      style={{ height: HEIGHT + AXIS_HEIGHT * 2 }}
    >
      {day.status === 'loading' ? (
        <p className="text-[12px] text-slate-400">Loading {day.date}…</p>
      ) : day.status === 'error' ? (
        <p className="text-[12px] leading-relaxed text-rose-600">{day.error}</p>
      ) : day.stored ? (
        // Already processed, so it loads itself the moment it scrolls into view.
        <p className="text-[12px] text-slate-300">…</p>
      ) : (
        <>
          <p className="text-[12px] leading-relaxed text-slate-400">
            This day has not been reconstructed yet.
          </p>
          <button
            type="button"
            onClick={() => onLoadDay(day.date)}
            data-testid={`collapsed-load-${day.date}`}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12px] font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800"
          >
            Fetch this day
          </button>
          <p className="text-[10.5px] leading-relaxed text-slate-400">
            Goes out to your sources; can take a minute.
          </p>
        </>
      )}
    </div>
  );
}

/**
 * The event's real extent, ignoring the midnight clipping.
 *
 * A period that crosses midnight is stored once per day it touches, each copy
 * cut at the boundary. The feature-engineering rules keep the true span in
 * `fullStart`/`fullEnd` precisely so a label can say "8:32 PM – 12:26 AM"
 * rather than the clipped "8:32 PM – 12:00 AM", which describes an awakening
 * that never happened.
 */
export function trueSpan(event: TimelineEvent): { start: string; end?: string | null } {
  const meta = event.metadata ?? {};
  const start = typeof meta.fullStart === 'string' ? meta.fullStart : event.startTime;
  const end = typeof meta.fullEnd === 'string' ? meta.fullEnd : event.endTime;
  return { start, end };
}

function LoadedDay({
  timeline,
  width,
  visible,
  curated,
  allEvents,
  selectedKey,
  onSelect,
  isFirstPanel,
}: {
  timeline: DayTimeline;
  width: number;
  visible: Set<string>;
  curated: Set<string>;
  allEvents: boolean;
  selectedKey: string | null;
  onSelect: (selection: Selection) => void;
  /** No earlier panel exists, so a continuation here has nothing to defer to. */
  isFirstPanel: boolean;
}) {
  const scale = useMemo(
    () => createScale(timeline.dayStart, timeline.dayEnd, width, timeline.localTimezone),
    [timeline.dayStart, timeline.dayEnd, timeline.localTimezone, width],
  );

  const items = useMemo(
    () => collapsedEvents(timeline.lanes, visible, curated, allEvents),
    [timeline.lanes, visible, curated, allEvents],
  );

  /**
   * Geometry per event, with two rules for periods cut at midnight.
   *
   * The bar runs to the panel's own edge rather than to the scale position of
   * midnight. The scale insets both ends by `PAD_LEFT`/`PAD_RIGHT` so the hour
   * labels are not clipped, which would otherwise leave a visible gap between
   * the two halves of one unbroken night's sleep.
   *
   * The node and label belong to the half where the period actually began, so
   * one sleep is announced once. The continuation carries only its bar — unless
   * this is the leftmost panel, where the opening half is not rendered at all
   * and suppressing it would lose the event entirely.
   */
  const geometry = useMemo(
    () =>
      items.map(({ event }) => {
        const startX = event.continuesBefore ? 0 : scale.x(event.startTime);
        const endX = event.continuesAfter
          ? width
          : event.endTime
            ? scale.x(event.endTime)
            : scale.x(event.startTime);
        return {
          startX,
          endX,
          nodeX: (startX + endX) / 2,
          announced: !event.continuesBefore || isFirstPanel,
        };
      }),
    [items, scale, width, isFirstPanel],
  );

  /**
   * Place each label on the first row — alternating above and below the
   * baseline — where it does not overlap one already placed. A label that fits
   * nowhere is dropped rather than drawn on top of its neighbour; the node,
   * tooltip and details panel still carry it.
   */
  const placements = useMemo(() => {
    const rowsAbove: [number, number][][] = [[], []];
    const rowsBelow: [number, number][][] = [[], []];

    return items.map(({ event }, index) => {
      // A continuation reserves no room: it is drawn as bar only.
      if (!geometry[index].announced) return { visible: false, above: true, tier: 0 };

      const centre = geometry[index].nodeX;
      const span = trueSpan(event);
      const labelWidth =
        Math.max(
          approximateTextWidth(event.label, 11.5),
          approximateTextWidth(
            formatTimeRange(span.start, span.end, timeline.localTimezone),
            10,
          ),
        ) + 12;
      const box: [number, number] = [centre - labelWidth / 2, centre + labelWidth / 2];

      const candidates: { rows: [number, number][][]; index: number; above: boolean }[] = [
        { rows: rowsAbove, index: 0, above: true },
        { rows: rowsBelow, index: 0, above: false },
        { rows: rowsAbove, index: 1, above: true },
        { rows: rowsBelow, index: 1, above: false },
      ];

      for (const candidate of candidates) {
        const occupied = candidate.rows[candidate.index];
        const collides = occupied.some(([low, high]) => box[0] < high && box[1] > low);
        if (!collides) {
          occupied.push(box);
          return { visible: true, above: candidate.above, tier: candidate.index };
        }
      }
      return { visible: false, above: true, tier: 0 };
    });
  }, [items, geometry, timeline.localTimezone]);

  return (
    <div style={{ width }}>
      <AxisRow scale={scale} position="top" />
      <svg
        width={width}
        height={HEIGHT}
        className="block"
        role="group"
        aria-label={`Collapsed timeline for ${timeline.date} with ${items.length} major events`}
      >
        <GridLines scale={scale} height={HEIGHT} />
        <line x1={0} x2={width} y1={BASELINE} y2={BASELINE} stroke="#e2e8f0" strokeWidth={1.4} />

        {items.length === 0 ? (
          <text x={width / 2} y={BASELINE - 10} textAnchor="middle" fontSize={12} fill="#94a3b8">
            No major events
          </text>
        ) : null}

        {items.map(({ event, lane }, index) => {
          const theme = accentTheme(lane.accent);
          const { startX, endX, nodeX, announced } = geometry[index];
          const key = `event:${event.id}`;
          const selected = selectedKey === key;
          const { visible, above, tier } = placements[index];
          const labelY = above ? BASELINE - 34 - tier * 32 : BASELINE + 44 + tier * 32;

          // Square off the cut end so the two halves of one period read as a
          // single unbroken bar across the join rather than two capsules.
          const radius = event.continuesBefore || event.continuesAfter ? 0 : 4;

          return (
            <Mark
              key={event.id}
              id={event.id}
              label={describeEvent(event, timeline.localTimezone)}
              selected={selected}
              onSelect={() =>
                onSelect({ kind: 'event', laneId: lane.id, event, date: timeline.date })
              }
            >
              <title>{eventTooltip(event, timeline.localTimezone)}</title>
              {endX - startX > 2 ? (
                <rect
                  x={startX}
                  y={BASELINE - 4}
                  width={Math.max(endX - startX, 3)}
                  height={8}
                  rx={radius}
                  fill={theme.fill}
                  opacity={0.85}
                />
              ) : null}
              {announced ? (
                <>
                  <circle
                    cx={nodeX}
                    cy={BASELINE}
                    r={selected ? 13 : 11}
                    fill="#ffffff"
                    stroke={selected ? theme.stroke : theme.fill}
                    strokeWidth={selected ? 2.4 : 1.6}
                  />
                  <g
                    transform={`translate(${nodeX - 7}, ${BASELINE - 7})`}
                    color={theme.stroke}
                    pointerEvents="none"
                  >
                    <LaneIcon laneId={lane.id} size={14} strokeWidth={1.8} />
                  </g>
                </>
              ) : null}
              {visible ? (
                <>
                  <line
                    x1={nodeX}
                    x2={nodeX}
                    y1={above ? BASELINE - 12 : BASELINE + 12}
                    y2={above ? labelY + 6 : labelY - 12}
                    stroke="#cbd5e1"
                    strokeWidth={1}
                    pointerEvents="none"
                  />
                  {/* The words are part of the mark, so clicking them selects
                      it. They used to sit in a `pointerEvents: none` group,
                      which made the most obvious thing to click — the event's
                      own name — the one thing that did nothing. */}
                  <text
                    x={nodeX}
                    y={labelY}
                    textAnchor="middle"
                    fontSize={11.5}
                    fontWeight={600}
                    fill="#0f2744"
                  >
                    {event.label}
                  </text>
                  <text x={nodeX} y={labelY + 13} textAnchor="middle" fontSize={10} fill="#64748b">
                    {/* The real span, not the half cut off at midnight. */}
                    {formatTimeRange(
                      trueSpan(event).start,
                      trueSpan(event).end,
                      timeline.localTimezone,
                    )}
                  </text>
                  {/* And the gaps between the glyphs, so a click landing
                      between two words is not a miss. */}
                  <rect
                    x={nodeX - labelHalfWidth(event.label)}
                    y={labelY - 12}
                    width={labelHalfWidth(event.label) * 2}
                    height={29}
                    fill="transparent"
                  />
                  {/* The column the leader line runs down, joining the caption
                      to the baseline. Without it the middle of the mark — where
                      a pointer aimed at "the event" most often lands — is a
                      hole between the two halves of the same thing. */}
                  <rect
                    x={nodeX - 11}
                    y={above ? labelY - 12 : BASELINE - 13}
                    width={22}
                    height={above ? BASELINE + 13 - (labelY - 12) : labelY + 17 - (BASELINE - 13)}
                    fill="transparent"
                  />
                </>
              ) : null}

              {/* A bar is eight pixels tall and a glyph twenty-two across:
                  both are small targets, and the centre of this mark's own
                  bounding box lands in the empty space between the label and
                  the baseline. These make the whole mark clickable. */}
              <rect
                x={startX - 2}
                y={BASELINE - 7}
                width={Math.max(endX - startX, 4) + 4}
                height={14}
                fill="transparent"
              />
              {announced ? (
                <rect
                  x={nodeX - 13}
                  y={BASELINE - 13}
                  width={26}
                  height={26}
                  fill="transparent"
                />
              ) : null}
            </Mark>
          );
        })}
      </svg>
      <AxisRow scale={scale} position="bottom" />
    </div>
  );
}
