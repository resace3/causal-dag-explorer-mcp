/**
 * Collapsed mode: one chronological line answering "what were the major
 * observable events yesterday?".
 *
 * No causal arrows, no delayed-effect edges, no connections between events —
 * only the events themselves on the shared time axis.
 */

import { useMemo } from 'react';
import { LaneIcon } from '../components/Icons';
import { useElementWidth } from '../hooks/useElementWidth';
import { Mark, approximateTextWidth, describeEvent, eventTooltip } from '../lanes/shared';
import type { DayTimeline, Lane, Selection, TimelineEvent } from '../types/timeline';
import { AXIS_HEIGHT, LANE_LABEL_WIDTH, MAJOR_CATEGORIES, accentTheme } from '../utilities/lanes';
import { formatTimeRange } from '../utilities/time';
import { AxisRow, GridLines } from './Axis';
import { createScale } from './scale';

const HEIGHT = 250;
const BASELINE = 132;
const MIN_PLOT_WIDTH = 560;

export interface MajorEvent {
  event: TimelineEvent;
  lane: Lane;
}

/** Selects the events a person would list if asked what happened yesterday. */
export function majorEvents(lanes: Lane[]): MajorEvent[] {
  const chosen: MajorEvent[] = [];
  for (const lane of lanes) {
    if (!lane.available) continue;
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

interface CollapsedTimelineProps {
  timeline: DayTimeline;
  lanes: Lane[];
  selectedKey: string | null;
  onSelect: (selection: Selection) => void;
  zoom: number;
}

export function CollapsedTimeline({
  timeline,
  lanes,
  selectedKey,
  onSelect,
  zoom,
}: CollapsedTimelineProps) {
  const { ref, width } = useElementWidth<HTMLDivElement>(900);
  const plotWidth = Math.max(width, MIN_PLOT_WIDTH) * zoom;

  const scale = useMemo(
    () => createScale(timeline.dayStart, timeline.dayEnd, plotWidth, timeline.localTimezone),
    [timeline.dayStart, timeline.dayEnd, timeline.localTimezone, plotWidth],
  );

  const items = useMemo(() => majorEvents(lanes), [lanes]);

  /**
   * Place each label on the first row — alternating above and below the
   * baseline — where it does not overlap one already placed. A label that fits
   * nowhere is dropped rather than drawn on top of its neighbour; the node,
   * tooltip and details panel still carry it.
   */
  const placements = useMemo(() => {
    const rowsAbove: [number, number][][] = [[], []];
    const rowsBelow: [number, number][][] = [[], []];

    return items.map(({ event }) => {
      const startX = scale.x(event.startTime);
      const endX = event.endTime ? scale.x(event.endTime) : startX;
      const centre = (startX + endX) / 2;
      const width =
        Math.max(
          approximateTextWidth(event.label, 11.5),
          approximateTextWidth(formatTimeRange(event.startTime, event.endTime, timeline.localTimezone), 10),
        ) + 12;
      const box: [number, number] = [centre - width / 2, centre + width / 2];

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
  }, [items, scale, timeline.localTimezone]);

  return (
    <div className="flex" data-testid="timeline-collapsed">
      <div
        className="shrink-0 border-r border-slate-100 bg-white"
        style={{ width: LANE_LABEL_WIDTH }}
      >
        <div style={{ height: AXIS_HEIGHT }} />
        <div className="flex items-center gap-3 px-5" style={{ height: HEIGHT }}>
          <span className="min-w-0">
            <span className="block text-[13.5px] font-semibold leading-tight text-slate-800">
              Major events
            </span>
            <span className="mt-0.5 block text-[11.5px] leading-tight text-slate-500">
              {items.length} observable events
            </span>
          </span>
        </div>
        <div style={{ height: AXIS_HEIGHT }} />
      </div>

      <div ref={ref} className="min-w-0 flex-1 overflow-x-auto overflow-y-hidden">
        <div style={{ width: plotWidth }}>
          <AxisRow scale={scale} position="top" />
          <svg
            width={plotWidth}
            height={HEIGHT}
            className="block"
            role="group"
            aria-label={`Collapsed timeline with ${items.length} major events`}
          >
            <GridLines scale={scale} height={HEIGHT} />
            <line
              x1={0}
              x2={plotWidth}
              y1={BASELINE}
              y2={BASELINE}
              stroke="#e2e8f0"
              strokeWidth={1.4}
            />

            {items.map(({ event, lane }, index) => {
              const theme = accentTheme(lane.accent);
              const startX = scale.x(event.startTime);
              const endX = event.endTime ? scale.x(event.endTime) : startX;
              const nodeX = (startX + endX) / 2;
              const key = `event:${event.id}`;
              const selected = selectedKey === key;
              const { visible, above, tier } = placements[index];
              const labelY = above
                ? BASELINE - 34 - tier * 32
                : BASELINE + 44 + tier * 32;

              return (
                <Mark
                  key={event.id}
                  id={event.id}
                  label={describeEvent(event, timeline.localTimezone)}
                  selected={selected}
                  onSelect={() => onSelect({ kind: 'event', laneId: lane.id, event })}
                >
                  <title>{eventTooltip(event, timeline.localTimezone)}</title>
                  {endX - startX > 2 ? (
                    <rect
                      x={startX}
                      y={BASELINE - 4}
                      width={Math.max(endX - startX, 3)}
                      height={8}
                      rx={4}
                      fill={theme.fill}
                      opacity={0.85}
                    />
                  ) : null}
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
                  {visible ? (
                    <g pointerEvents="none">
                      <line
                        x1={nodeX}
                        x2={nodeX}
                        y1={above ? BASELINE - 12 : BASELINE + 12}
                        y2={above ? labelY + 6 : labelY - 12}
                        stroke="#cbd5e1"
                        strokeWidth={1}
                      />
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
                      <text
                        x={nodeX}
                        y={labelY + 13}
                        textAnchor="middle"
                        fontSize={10}
                        fill="#64748b"
                      >
                        {formatTimeRange(event.startTime, event.endTime, timeline.localTimezone)}
                      </text>
                    </g>
                  ) : null}
                </Mark>
              );
            })}
          </svg>
          <AxisRow scale={scale} position="bottom" />
        </div>
      </div>
    </div>
  );
}
