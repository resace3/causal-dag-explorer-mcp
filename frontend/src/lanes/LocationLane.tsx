/**
 * Phone location.
 *
 * Two rows on the shared axis: the zone the device tracker reported, and the
 * place name it geocoded to. No coordinates exist in the payload, so none can
 * be drawn.
 */

import { accentTheme } from '../utilities/lanes';
import { formatTimeRange } from '../utilities/time';
import {
  IntervalBar,
  Mark,
  MissingDataDefs,
  approximateTextWidth,
  describeEvent,
  eventTooltip,
  type LaneRenderProps,
} from './shared';

const ZONE_TOP = 10;
const ZONE_HEIGHT = 24;
const PLACE_TOP = ZONE_TOP + ZONE_HEIGHT + 8;
const PLACE_HEIGHT = 26;

const ZONE_STYLES: Record<string, { fill: string; stroke: string; text: string }> = {
  zone_home: { fill: '#e0e7ff', stroke: '#c3ccfb', text: '#4338ca' },
  zone_away: { fill: '#f1f4f8', stroke: '#dde4ed', text: '#5b6b7f' },
  zone_named: { fill: '#e8e6fd', stroke: '#cdc9f8', text: '#5b46c9' },
};

export function LocationLane({
  lane,
  scale,
  timeZone,
  selectedKey,
  onSelect,
}: LaneRenderProps) {
  const theme = accentTheme(lane.accent);
  const patternId = `missing-${lane.id}`;
  const zones = lane.events.filter((event) => (event.category ?? '').startsWith('zone_'));
  const places = lane.events.filter((event) => event.category === 'place');

  return (
    <>
      <MissingDataDefs id={patternId} />

      {zones.map((event) => {
        const x = scale.x(event.startTime);
        const width = Math.max(scale.x(event.endTime ?? event.startTime) - x, 3);
        const style = ZONE_STYLES[event.category ?? ''] ?? ZONE_STYLES.zone_named;
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
              y={ZONE_TOP}
              height={ZONE_HEIGHT}
              fill={style.fill}
              stroke={selected ? style.text : style.stroke}
              continuesBefore={event.continuesBefore}
              continuesAfter={event.continuesAfter}
            />
            {width > 62 ? (
              <text
                x={x + 12}
                y={ZONE_TOP + 16}
                fontSize={11}
                fontWeight={600}
                fill={style.text}
                pointerEvents="none"
              >
                {event.label}
                <tspan fontWeight={400} opacity={0.75} dx={8} fontSize={10}>
                  {width > 190 ? formatTimeRange(event.startTime, event.endTime, timeZone) : ''}
                </tspan>
              </text>
            ) : null}
          </Mark>
        );
      })}

      {places.map((event) => {
        const x = scale.x(event.startTime);
        const width = Math.max(scale.x(event.endTime ?? event.startTime) - x, 3);
        const key = `event:${event.id}`;
        const selected = selectedKey === key;
        const fits = width > approximateTextWidth(event.label, 11) + 26;
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
              x={x + 1}
              y={PLACE_TOP}
              width={Math.max(width - 2, 2)}
              height={PLACE_HEIGHT}
              rx={7}
              fill={theme.band}
              stroke={selected ? theme.stroke : theme.soft}
              strokeWidth={selected ? 1.8 : 1}
            />
            {fits ? (
              <g pointerEvents="none">
                <circle cx={x + 14} cy={PLACE_TOP + 13} r={3.2} fill={theme.fill} />
                <text
                  x={x + 24}
                  y={PLACE_TOP + 17}
                  fontSize={11}
                  fontWeight={600}
                  fill={theme.text}
                >
                  {event.label}
                </text>
              </g>
            ) : null}
          </Mark>
        );
      })}

      {places.length ? (
        <text
          x={6}
          y={PLACE_TOP + PLACE_HEIGHT + 13}
          fontSize={9.5}
          fill="#7c8a9c"
          pointerEvents="none"
        >
          Place names only — no coordinates are stored
        </text>
      ) : null}
    </>
  );
}
