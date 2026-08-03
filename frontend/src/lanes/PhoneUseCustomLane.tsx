/**
 * Phone use, from the usage-stats add-on.
 *
 * Same two-tier encoding as the Phone Use row above, deliberately: the rows
 * exist to be read against each other, and drawing the same quantity two
 * different ways would obstruct exactly that comparison.
 *
 * The summary line is where they differ. This source knows things the
 * companion app cannot see — how many times the phone was unlocked, and how
 * many times the screen was woken and put down again without one — so those
 * are named here rather than buried in a details panel.
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

function counts(sessions: TimelineEvent[]): Record<string, unknown> | null {
  for (const event of sessions) {
    const day = event.metadata?.dayCounts;
    if (day && typeof day === 'object') return day as Record<string, unknown>;
  }
  return null;
}

function summarise(sessions: TimelineEvent[], apps: TimelineEvent[]): string {
  const total = sessions.reduce((sum, event) => sum + minutesOf(event), 0);
  const hours = Math.floor(total / 60);
  const rest = Math.round(total % 60);
  const spent = hours ? `${hours}h ${rest}m` : `${rest}m`;
  const parts = [`${spent} in the foreground`];

  const day = counts(sessions);
  const unlocks = day?.unlocks;
  const glances = day?.glancesWithoutUnlock;
  if (typeof unlocks === 'number') parts.push(`${unlocks} unlocks`);
  // A glance is a wake that never became an unlock — a distinct thing, and the
  // reason this row is worth having beside the other one.
  if (typeof glances === 'number') parts.push(`${glances} glances`);
  if (apps.length) parts.push(`${apps.length} named app spells`);
  return parts.join(' · ');
}

export function PhoneUseCustomLane({
  lane,
  scale,
  height,
  timeZone,
  selectedKey,
  onSelect,
}: LaneRenderProps) {
  const theme = accentTheme(lane.accent);

  const sessions = lane.events.filter((event) => event.category === 'phone_custom_on');
  const apps = lane.events.filter((event) => event.category === 'phone_custom_app');

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
        {/* Segments here are seconds-accurate, so many are only a pixel or two
            wide; without a padded hit area most would be unclickable. */}
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
      {apps.map((event) => bar(event, APP_TOP, APP_HEIGHT, theme.fill, theme.stroke, '#ffffff'))}

      {sessions.length ? (
        <text x={6} y={height - 7} fontSize={9.5} fill="#7c8a9c" pointerEvents="none">
          {summarise(sessions, apps)}
        </text>
      ) : null}
    </>
  );
}
