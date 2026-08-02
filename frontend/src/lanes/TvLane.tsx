/**
 * The television, from Home Assistant.
 *
 * Two tiers, coarsest first: stretches with the set on, then what was playing.
 * Reading down a column says "TV on, showing King of the Hill".
 *
 * The band and the bars are drawn differently on purpose. The band is a weaker
 * claim — the set was powered on, which a paused episode and an idle menu both
 * satisfy — so it is a pale strip with no caption. The named spells sit on top
 * in solid colour, because those are the ones where something was actually
 * reported playing.
 */

import type { TimelineEvent } from '../types/timeline';
import { formatTimeRange } from '../utilities/time';
import { accentTheme } from '../utilities/lanes';
import {
  IntervalBar,
  Mark,
  describeEvent,
  eventTooltip,
  type LaneRenderProps,
} from './shared';

const BAND_TOP = 10;
const BAND_HEIGHT = 14;
const PROGRAMME_TOP = 30;
const PROGRAMME_HEIGHT = 26;

function minutesOf(event: TimelineEvent): number {
  const value = event.metadata?.durationMinutes;
  return typeof value === 'number' ? value : 0;
}

function summarise(sessions: TimelineEvent[], programmes: TimelineEvent[]): string {
  const total = sessions.reduce((sum, event) => sum + minutesOf(event), 0);
  const hours = Math.floor(total / 60);
  const rest = Math.round(total % 60);
  const spent = hours ? `${hours}h ${rest}m` : `${rest}m`;
  // "With the TV on", never "watching": the sensor reports the set's power
  // state, and nobody in the room is a thing it cannot see.
  const parts = [`${spent} with the TV on`];
  if (sessions.length) {
    parts.push(`${sessions.length} sitting${sessions.length === 1 ? '' : 's'}`);
  }
  if (programmes.length) {
    parts.push(`${programmes.length} named programme${programmes.length === 1 ? '' : 's'}`);
  }
  return parts.join(' · ');
}

export function TvLane({
  lane,
  scale,
  height,
  timeZone,
  selectedKey,
  onSelect,
}: LaneRenderProps) {
  const theme = accentTheme(lane.accent);

  const sessions = lane.events.filter((event) => event.category === 'tv_on');
  const programmes = lane.events.filter((event) => event.category === 'tv_playing');

  const bar = (
    event: TimelineEvent,
    y: number,
    barHeight: number,
    fill: string,
    stroke: string,
    labelColour: string | null,
  ) => {
    const x = scale.x(event.startTime);
    const width = Math.max(scale.x(event.endTime ?? event.startTime) - x, 2.5);
    const key = `event:${event.id}`;
    const selected = selectedKey === key;
    const label = labelColour && width > 48 ? event.label : null;

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
          x={x + 0.5}
          width={Math.max(width - 1, 2)}
          y={y}
          height={barHeight}
          fill={fill}
          stroke={selected ? theme.stroke : stroke}
          continuesBefore={event.continuesBefore}
          continuesAfter={event.continuesAfter}
        />
        {/* The on-band is 14px tall and a short sitting only a few px wide;
            without a padded hit area most of these are unclickable. */}
        <rect
          x={x - 2}
          y={y - 3}
          width={Math.max(width, 3) + 4}
          height={barHeight + 6}
          fill="transparent"
        />
        {label && labelColour ? (
          <text
            x={x + 8}
            y={y + barHeight / 2 + 4}
            fontSize={11}
            fontWeight={600}
            fill={labelColour}
            pointerEvents="none"
          >
            {label}
            <tspan fontWeight={400} opacity={0.75} dx={8} fontSize={10}>
              {width > 180 ? formatTimeRange(event.startTime, event.endTime, timeZone) : ''}
            </tspan>
          </text>
        ) : null}
      </Mark>
    );
  };

  return (
    <>
      {sessions.map((event) => bar(event, BAND_TOP, BAND_HEIGHT, theme.soft, theme.fill, null))}
      {programmes.map((event) =>
        bar(event, PROGRAMME_TOP, PROGRAMME_HEIGHT, theme.fill, theme.stroke, '#ffffff'),
      )}

      {sessions.length ? (
        <text x={6} y={height - 7} fontSize={9.5} fill="#7c8a9c" pointerEvents="none">
          {summarise(sessions, programmes)}
        </text>
      ) : null}
    </>
  );
}
