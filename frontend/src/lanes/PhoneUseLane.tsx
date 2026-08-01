/**
 * Phone use, from the Home Assistant companion app.
 *
 * Two tiers, coarsest first: stretches with the screen on, then which app was
 * in front. Reading down a column says "phone in hand, in TikTok".
 *
 * A phone is picked up far more often than a computer is sat at, so the top
 * tier is a thin band rather than a labelled bar: forty unlocks with forty
 * captions would be a smear. The named spells carry the labels.
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
const APP_TOP = 30;
const APP_HEIGHT = 26;

function minutesOf(event: TimelineEvent): number {
  const value = event.metadata?.durationMinutes;
  return typeof value === 'number' ? value : 0;
}

function summarise(sessions: TimelineEvent[], apps: TimelineEvent[]): string {
  const total = sessions.reduce((sum, event) => sum + minutesOf(event), 0);
  const hours = Math.floor(total / 60);
  const rest = Math.round(total % 60);
  const spent = hours ? `${hours}h ${rest}m` : `${rest}m`;
  const parts = [`${spent} with the screen on`];
  if (sessions.length) {
    parts.push(`${sessions.length} session${sessions.length === 1 ? '' : 's'}`);
  }
  if (apps.length) parts.push(`${apps.length} named app spells`);
  return parts.join(' · ');
}

export function PhoneUseLane({
  lane,
  scale,
  height,
  timeZone,
  selectedKey,
  onSelect,
}: LaneRenderProps) {
  const theme = accentTheme(lane.accent);

  const sessions = lane.events.filter((event) => event.category === 'phone_on');
  const apps = lane.events.filter((event) => event.category === 'phone_app');

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
        {/* A screen-on band is 14px tall and often only a few px wide; without
            a padded hit area most of these are unclickable. */}
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
      {sessions.map((event) =>
        bar(event, BAND_TOP, BAND_HEIGHT, theme.soft, theme.fill, null),
      )}
      {apps.map((event) => bar(event, APP_TOP, APP_HEIGHT, theme.fill, theme.stroke, '#ffffff'))}

      {sessions.length ? (
        <text x={6} y={height - 7} fontSize={9.5} fill="#7c8a9c" pointerEvents="none">
          {summarise(sessions, apps)}
        </text>
      ) : null}
    </>
  );
}
