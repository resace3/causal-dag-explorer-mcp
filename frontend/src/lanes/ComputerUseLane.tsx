/**
 * Computer use, from ActivityWatch.
 *
 * Three tiers, coarsest first: stretches at the machine, then which application
 * had focus, then which site a browser tab was on. Reading down a column says
 * "at the desk, in the editor" or "at the desk, in the browser, on github.com".
 *
 * Every stretch at the machine is drawn, including the short ones — a
 * four-minute burst between two breaks is real, and a lane that dropped it
 * would show an empty evening for a day full of focus events.
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

// The three tiers stack tightly enough to read as one column. The browsing row
// keeps its place even on a day with no browsing, so the application bars do
// not shift down the row when a browser extension happens to be quiet.
const BAND_TOP = 8;
const BAND_HEIGHT = 20;
const APP_TOP = 33;
const APP_HEIGHT = 24;
const WEB_TOP = 62;
const WEB_HEIGHT = 9;

function minutesOf(event: TimelineEvent): number {
  const value = event.metadata?.durationMinutes;
  return typeof value === 'number' ? value : 0;
}

function summarise(sessions: TimelineEvent[], apps: TimelineEvent[]): string {
  const total = sessions.reduce((sum, event) => sum + minutesOf(event), 0);
  const hours = Math.floor(total / 60);
  const rest = Math.round(total % 60);
  const spent = hours ? `${hours}h ${rest}m` : `${rest}m`;
  // "Sessions" counts only the stretches that met the configured minimum, so
  // the number matches what the threshold means rather than counting blips.
  const counted = sessions.filter((event) => event.metadata?.brief !== true).length;
  const parts = [`${spent} at the computer`];
  if (counted) parts.push(`${counted} session${counted === 1 ? '' : 's'}`);
  if (apps.length) parts.push(`${apps.length} named application spells`);
  return parts.join(' · ');
}

export function ComputerUseLane({
  lane,
  scale,
  height,
  timeZone,
  selectedKey,
  onSelect,
}: LaneRenderProps) {
  const theme = accentTheme(lane.accent);

  const sessions = lane.events.filter((event) => event.category === 'at_computer');
  const apps = lane.events.filter((event) => event.category === 'app_session');
  const sites = lane.events.filter((event) => event.category === 'browsing');

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
    const label = labelColour && width > 54 ? event.label : null;

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
        {label && labelColour ? (
          <text
            x={x + 9}
            y={y + barHeight / 2 + 4}
            fontSize={11}
            fontWeight={600}
            fill={labelColour}
            pointerEvents="none"
          >
            {label}
            <tspan fontWeight={400} opacity={0.75} dx={8} fontSize={10}>
              {width > 190 ? formatTimeRange(event.startTime, event.endTime, timeZone) : ''}
            </tspan>
          </text>
        ) : null}
      </Mark>
    );
  };

  return (
    <>
      {sessions.map((event) => bar(event, BAND_TOP, BAND_HEIGHT, theme.soft, theme.fill, theme.text))}
      {apps.map((event) => bar(event, APP_TOP, APP_HEIGHT, theme.fill, theme.stroke, '#ffffff'))}
      {sites.map((event) => bar(event, WEB_TOP, WEB_HEIGHT, theme.stroke, theme.stroke, null))}

      {/* Site names sit beside their bar: at 9px tall there is no room inside. */}
      {sites.map((event) => {
        const x = scale.x(event.startTime);
        const width = scale.x(event.endTime ?? event.startTime) - x;
        return width > 70 ? (
          <text
            key={`${event.id}-label`}
            x={x + 5}
            y={WEB_TOP + WEB_HEIGHT + 11}
            fontSize={9.5}
            fill={theme.text}
            pointerEvents="none"
          >
            {event.label}
          </text>
        ) : null;
      })}

      {sessions.length ? (
        <text x={6} y={height - 7} fontSize={9.5} fill="#7c8a9c" pointerEvents="none">
          {summarise(sessions, apps)}
        </text>
      ) : null}
    </>
  );
}
