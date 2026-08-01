/**
 * Presence and motion.
 *
 * Home / away blocks on top, arrival and departure markers beneath them, and
 * motion reports as small ticks on a baseline. Only occupancy states are shown;
 * no coordinates exist in the data model at all.
 */

import type { TimelineEvent } from '../types/timeline';
import { formatTimeRange } from '../utilities/time';
import {
  IntervalBar,
  Mark,
  MissingDataDefs,
  describeEvent,
  eventTooltip,
  type LaneRenderProps,
} from './shared';

const BLOCK_TOP = 8;
const BLOCK_HEIGHT = 24;
const TRANSITION_Y = BLOCK_TOP + BLOCK_HEIGHT + 6;

const PRESENCE_STYLES: Record<string, { fill: string; stroke: string; text: string }> = {
  presence_home: { fill: '#d8f4fb', stroke: '#a8e2f0', text: '#0e7490' },
  presence_away: { fill: '#f1f4f8', stroke: '#dde4ed', text: '#5b6b7f' },
  presence_unknown: { fill: '#f7f8fa', stroke: '#e2e8f0', text: '#7c8a9c' },
};

function isPresenceBlock(event: TimelineEvent): boolean {
  return (event.category ?? '').startsWith('presence_');
}

export function PresenceLane({
  lane,
  scale,
  height,
  timeZone,
  selectedKey,
  onSelect,
}: LaneRenderProps) {
  const patternId = `missing-${lane.id}`;
  const motionBaseline = height - 24;
  const inactivityY = height - 13;

  const blocks = lane.events.filter(isPresenceBlock);
  const transitions = lane.events.filter(
    (event) => event.category === 'arrived_home' || event.category === 'left_home',
  );
  const motion = lane.events.filter((event) => event.category === 'motion');
  const inactivity = lane.events.filter((event) => event.category === 'inactivity');
  const doors = lane.events.filter((event) => event.category === 'door');

  return (
    <>
      <MissingDataDefs id={patternId} />

      {blocks.map((event) => {
        const x = scale.x(event.startTime);
        const width = Math.max(scale.x(event.endTime ?? event.startTime) - x, 3);
        const style = PRESENCE_STYLES[event.category ?? ''] ?? PRESENCE_STYLES.presence_unknown;
        const key = `event:${event.id}`;
        const selected = selectedKey === key;
        return (
          <Mark
            key={event.id}
            id={event.id}
            label={describeEvent(event, timeZone)}
            selected={selected}
            onSelect={() => onSelect({ kind: 'event', laneId: lane.id, event })}
          >
            <title>{eventTooltip(event, timeZone)}</title>
            <IntervalBar
              x={x + 1}
              width={Math.max(width - 2, 2)}
              y={BLOCK_TOP}
              height={BLOCK_HEIGHT}
              fill={style.fill}
              stroke={selected ? style.text : style.stroke}
              continuesBefore={event.continuesBefore}
              continuesAfter={event.continuesAfter}
            />
            {width > 66 ? (
              <text
                x={x + 12}
                y={BLOCK_TOP + 17}
                fontSize={11}
                fontWeight={600}
                fill={style.text}
                pointerEvents="none"
              >
                {event.label}
                <tspan fontWeight={400} opacity={0.75} dx={8} fontSize={10}>
                  {width > 168 ? formatTimeRange(event.startTime, event.endTime, timeZone) : ''}
                </tspan>
              </text>
            ) : null}
          </Mark>
        );
      })}

      {inactivity.map((event) => {
        const x = scale.x(event.startTime);
        const width = Math.max(scale.x(event.endTime ?? event.startTime) - x, 3);
        const key = `event:${event.id}`;
        const selected = selectedKey === key;
        return (
          <Mark
            key={event.id}
            id={event.id}
            label={describeEvent(event, timeZone)}
            selected={selected}
            onSelect={() => onSelect({ kind: 'event', laneId: lane.id, event })}
          >
            <title>{eventTooltip(event, timeZone)}</title>
            <rect
              x={x}
              y={inactivityY}
              width={width}
              height={selected ? 6 : 4}
              rx={2}
              fill="#cbd5e1"
            />
          </Mark>
        );
      })}

      <line
        x1={0}
        x2={scale.width}
        y1={motionBaseline}
        y2={motionBaseline}
        stroke="#e8edf4"
        strokeWidth={1}
      />

      {/* Door and window openings sit on the same baseline as motion. */}
      {doors.map((event) => {
        const x = scale.x(event.startTime);
        const key = `event:${event.id}`;
        const selected = selectedKey === key;
        return (
          <Mark
            key={event.id}
            id={event.id}
            label={describeEvent(event, timeZone)}
            selected={selected}
            onSelect={() => onSelect({ kind: 'event', laneId: lane.id, event })}
          >
            <title>{eventTooltip(event, timeZone)}</title>
            <path
              d={`M${x} ${motionBaseline - 11} l4.5 5.5 -4.5 5.5 -4.5 -5.5 z`}
              fill="#f59e0b"
              stroke="#ffffff"
              strokeWidth={selected ? 1.6 : 0.8}
            />
            <rect
              x={x - 6}
              y={motionBaseline - 13}
              width={12}
              height={15}
              fill="transparent"
            />
          </Mark>
        );
      })}

      {motion.map((event) => {
        const x = scale.x(event.startTime);
        const key = `event:${event.id}`;
        const selected = selectedKey === key;
        return (
          <Mark
            key={event.id}
            id={event.id}
            label={describeEvent(event, timeZone)}
            selected={selected}
            onSelect={() => onSelect({ kind: 'event', laneId: lane.id, event })}
          >
            <title>{eventTooltip(event, timeZone)}</title>
            <rect
              x={x - 1}
              y={motionBaseline - (selected ? 13 : 9)}
              width={selected ? 3 : 2}
              height={selected ? 13 : 9}
              rx={1}
              fill="#0891b2"
              opacity={selected ? 1 : 0.62}
            />
            <rect
              x={x - 5}
              y={motionBaseline - 15}
              width={10}
              height={18}
              fill="transparent"
            />
          </Mark>
        );
      })}

      {transitions.map((event, index) => {
        const x = scale.x(event.startTime);
        const key = `event:${event.id}`;
        const selected = selectedKey === key;
        const arriving = event.category === 'arrived_home';
        // Drop a transition label when either neighbour is close enough to collide.
        const previousX = index > 0 ? scale.x(transitions[index - 1].startTime) : -Infinity;
        const nextX =
          index + 1 < transitions.length ? scale.x(transitions[index + 1].startTime) : Infinity;
        const showLabel = x - previousX > 82 && nextX - x > 68;
        return (
          <Mark
            key={event.id}
            id={event.id}
            label={describeEvent(event, timeZone)}
            selected={selected}
            onSelect={() => onSelect({ kind: 'event', laneId: lane.id, event })}
          >
            <title>{eventTooltip(event, timeZone)}</title>
            <path
              d={`M${x} ${TRANSITION_Y} l5 5 -5 5 -5 -5 z`}
              fill={arriving ? '#0891b2' : '#94a3b8'}
              stroke="#ffffff"
              strokeWidth={selected ? 1.8 : 1}
            />
            {showLabel ? (
              <text
                x={x + 9}
                y={TRANSITION_Y + 9}
                fontSize={10}
                fill="#5b6b7f"
                pointerEvents="none"
              >
                {event.label}
              </text>
            ) : null}
          </Mark>
        );
      })}

      {(() => {
        const counts = [
          motion.length ? `${motion.length} motion reports` : null,
          doors.length ? `${doors.length} door openings` : null,
        ].filter(Boolean);
        return counts.length ? (
          <text x={6} y={motionBaseline + 12} fontSize={9.5} fill="#7c8a9c" pointerEvents="none">
            {counts.join(' · ')}
          </text>
        ) : null;
      })()}
    </>
  );
}
