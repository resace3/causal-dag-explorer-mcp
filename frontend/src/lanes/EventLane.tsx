/**
 * Lanes made of discrete marks: Activity, Sleep and HRV.
 *
 * Each event gets a circular node with an icon, a two-line label, and — when it
 * has a duration — a bar under the node showing how long it lasted.
 */

import { LaneIcon } from '../components/Icons';
import type { DayScale } from '../timeline/scale';
import type { Selection, TimelineEvent } from '../types/timeline';
import { accentTheme } from '../utilities/lanes';
import { formatTimeRange } from '../utilities/time';
import {
  IntervalBar,
  Mark,
  MissingDataDefs,
  approximateTextWidth,
  describeEvent,
  eventTooltip,
  placeLabels,
  type LaneRenderProps,
} from './shared';

const NODE_RADIUS = 15;
const LABEL_OFFSET = 22;

interface Geometry {
  event: TimelineEvent;
  startX: number;
  endX: number;
  nodeX: number;
}

function geometry(events: TimelineEvent[], scale: DayScale): Geometry[] {
  return events.map((event) => {
    const startX = scale.x(event.startTime);
    const endX = event.endTime ? scale.x(event.endTime) : startX;
    return { event, startX, endX, nodeX: (startX + endX) / 2 };
  });
}

export function EventLane({
  lane,
  scale,
  height,
  timeZone,
  selectedKey,
  onSelect,
}: LaneRenderProps) {
  const theme = accentTheme(lane.accent);
  const patternId = `missing-${lane.id}`;
  const nodeY = height / 2 - 8;
  const baseline = nodeY + 27;

  const marks = geometry(lane.events, scale);
  // The node circles are reserved space: a label may never cross one.
  const nodeBoxes: [number, number][] = marks.map(({ nodeX }) => [
    nodeX - NODE_RADIUS - 2,
    nodeX + NODE_RADIUS + 2,
  ]);
  const labelWidths = marks.map(({ event }) =>
    Math.max(
      approximateTextWidth(event.label, 12),
      approximateTextWidth(formatTimeRange(event.startTime, event.endTime, timeZone), 10.5),
    ),
  );
  const labels = placeLabels(
    marks.map(({ nodeX }, index) => ({
      x: nodeX,
      offset: LABEL_OFFSET,
      width: labelWidths[index] + 4,
    })),
    scale,
    10,
    nodeBoxes,
  );

  return (
    <>
      <MissingDataDefs id={patternId} />
      <line
        x1={0}
        x2={scale.width}
        y1={baseline}
        y2={baseline}
        stroke="#e8edf4"
        strokeWidth={1}
      />

      {marks.map(({ event, startX, endX, nodeX }, index) => {
        const key = `event:${event.id}`;
        const selected = selectedKey === key;
        const missing = event.category === 'missing_data';
        const hasDuration = Boolean(event.endTime) && endX - startX > 1.5;
        const label = labels[index];

        return (
          <Mark
            key={event.id}
            id={event.id}
            label={describeEvent(event, timeZone)}
            selected={selected}
            onSelect={() => onSelect({ kind: 'event', laneId: lane.id, event } as Selection)}
          >
            <title>{eventTooltip(event, timeZone)}</title>

            {/*
              One hit area spanning the node and its duration bar. Without it
              the gap between the two is dead space inside the mark's own
              bounding box, and a click aimed at the event lands on nothing.
            */}
            {(() => {
              const left = Math.min(startX, nodeX - NODE_RADIUS) - 3;
              const right = Math.max(endX, nodeX + NODE_RADIUS) + 3;
              return (
                <rect
                  x={left}
                  y={nodeY - NODE_RADIUS - 3}
                  width={Math.max(right - left, 8)}
                  height={baseline + 9 - (nodeY - NODE_RADIUS - 3)}
                  fill="transparent"
                />
              );
            })()}

            {hasDuration ? (
              /* One plain bar. Sleep used to shade its stages here; the row
                 reports duration now and no event carries a hypnogram. */
              <IntervalBar
                x={startX}
                width={endX - startX}
                y={baseline - 5}
                height={10}
                fill={missing ? `url(#${patternId})` : theme.fill}
                opacity={missing ? 1 : 0.85}
                continuesBefore={event.continuesBefore}
                continuesAfter={event.continuesAfter}
                stroke={missing ? '#c9d2de' : undefined}
              />
            ) : (
              <>
                {/* A nightly value summarises a window; show which one. */}
                {event.metadata?.coversSleepStart && event.metadata?.coversSleepEnd ? (
                  <g pointerEvents="none">
                    <line
                      x1={scale.x(event.metadata.coversSleepStart as string)}
                      x2={scale.x(event.metadata.coversSleepEnd as string)}
                      y1={baseline}
                      y2={baseline}
                      stroke={theme.fill}
                      strokeWidth={1.4}
                      opacity={0.55}
                    />
                    {[event.metadata.coversSleepStart, event.metadata.coversSleepEnd].map(
                      (edge) => (
                        <line
                          key={edge as string}
                          x1={scale.x(edge as string)}
                          x2={scale.x(edge as string)}
                          y1={baseline - 4}
                          y2={baseline + 4}
                          stroke={theme.fill}
                          strokeWidth={1.4}
                          opacity={0.55}
                        />
                      ),
                    )}
                  </g>
                ) : null}
                <circle cx={startX} cy={baseline} r={4} fill={theme.fill} />
              </>
            )}

            <g transform={`translate(${nodeX}, ${nodeY})`}>
              <circle
                r={NODE_RADIUS}
                fill="#ffffff"
                stroke={selected ? theme.stroke : theme.fill}
                strokeWidth={selected ? 2.4 : 1.5}
              />
              <g transform="translate(-9, -9)" color={theme.stroke} pointerEvents="none">
                <LaneIcon laneId={lane.id} size={18} strokeWidth={1.7} />
              </g>
            </g>

            {label.visible ? (
              <g transform={`translate(${label.x}, ${nodeY})`}>
                {/*
                  The label is part of the mark's hit area, not decoration:
                  people click the words. Leaving it pointer-transparent also
                  put a dead zone at the centre of the mark's bounding box.
                */}
                <rect
                  x={label.anchor === 'start' ? -6 : -labelWidths[index] - 6}
                  y={-15}
                  width={labelWidths[index] + 12}
                  height={30}
                  fill="transparent"
                />
                <text
                  textAnchor={label.anchor}
                  y={-3}
                  className="tl-label-time"
                  fill="#64748b"
                  fontSize={10.5}
                  pointerEvents="none"
                >
                  {formatTimeRange(event.startTime, event.endTime, timeZone)}
                </text>
                <text
                  textAnchor={label.anchor}
                  y={11}
                  className="tl-label-name"
                  fill="#0f2744"
                  fontSize={12}
                  fontWeight={600}
                  pointerEvents="none"
                >
                  {event.label}
                </text>
              </g>
            ) : null}
          </Mark>
        );
      })}
    </>
  );
}
