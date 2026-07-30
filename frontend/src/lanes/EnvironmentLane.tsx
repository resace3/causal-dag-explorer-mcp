/**
 * Environment lane: measured light-condition blocks over a compact
 * room-temperature sub-line, so several environmental variables stay readable
 * instead of being crushed into one line.
 */

import { MoonIcon, SunIcon } from '../components/Icons';
import { createValueScale } from '../timeline/scale';
import type { TimelineSeries } from '../types/timeline';
import { formatTimeRange } from '../utilities/time';
import {
  Mark,
  MissingDataDefs,
  describeEvent,
  eventTooltip,
  type LaneRenderProps,
} from './shared';

const BLOCK_TOP = 8;
const BLOCK_HEIGHT = 40;
const SERIES_TOP = 60;

interface BlockStyle {
  fill: string;
  stroke: string;
  text: string;
  icon: 'moon' | 'sun';
}

const LIGHT_STYLES: Record<string, BlockStyle> = {
  light_dark: { fill: '#eef1f6', stroke: '#dee4ec', text: '#4b5b6e', icon: 'moon' },
  light_dim: { fill: '#e9f0fa', stroke: '#d5e2f2', text: '#3c5f8a', icon: 'moon' },
  light_moderate: { fill: '#e1f0fd', stroke: '#c8e3f8', text: '#0b6394', icon: 'sun' },
  light_bright: { fill: '#d5eafd', stroke: '#b6dbf7', text: '#04618f', icon: 'sun' },
};

const MISSING_STYLE: BlockStyle = {
  fill: 'transparent',
  stroke: '#cfd7e2',
  text: '#7c8a9c',
  icon: 'moon',
};

export function EnvironmentLane({
  lane,
  scale,
  height,
  timeZone,
  selectedKey,
  onSelect,
}: LaneRenderProps) {
  const patternId = `missing-${lane.id}-blocks`;
  const series: TimelineSeries | undefined = lane.series[0];
  const seriesBottom = height - 14;

  const valueScale = series
    ? createValueScale(
        series.points.map((point) => point.value),
        SERIES_TOP,
        seriesBottom,
      )
    : null;

  return (
    <>
      <MissingDataDefs id={patternId} />

      {lane.events.map((event) => {
        const x = scale.x(event.startTime);
        const width = Math.max(scale.x(event.endTime ?? event.startTime) - x, 3);
        const missing = event.category === 'missing_data';
        const style = missing
          ? MISSING_STYLE
          : LIGHT_STYLES[event.category ?? ''] ?? LIGHT_STYLES.light_moderate;
        const key = `event:${event.id}`;
        const selected = selectedKey === key;
        const showIcon = width > 40;
        const showText = width > 62;
        const Icon = style.icon === 'sun' ? SunIcon : MoonIcon;

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
              y={BLOCK_TOP}
              width={Math.max(width - 2, 2)}
              height={BLOCK_HEIGHT}
              rx={8}
              fill={missing ? `url(#${patternId})` : style.fill}
              stroke={selected ? style.text : style.stroke}
              strokeWidth={selected ? 1.8 : 1}
            />
            {showIcon ? (
              <g
                transform={`translate(${x + 11}, ${BLOCK_TOP + 11})`}
                color={style.text}
                pointerEvents="none"
              >
                <Icon size={16} strokeWidth={1.6} />
              </g>
            ) : null}
            {showText ? (
              <g pointerEvents="none">
                <text
                  x={x + (showIcon ? 33 : 10)}
                  y={BLOCK_TOP + 17}
                  fontSize={11.5}
                  fontWeight={600}
                  fill={style.text}
                >
                  {missing ? 'No data' : event.label.replace(' light', '')}
                </text>
                <text
                  x={x + (showIcon ? 33 : 10)}
                  y={BLOCK_TOP + 31}
                  fontSize={10}
                  fill={style.text}
                  opacity={0.8}
                >
                  {formatTimeRange(event.startTime, event.endTime, timeZone)}
                </text>
              </g>
            ) : null}
          </Mark>
        );
      })}

      {series && valueScale ? (
        <g>
          <text x={6} y={SERIES_TOP - 4} fontSize={10} fill="#5b7186">
            {series.label} ({series.unit})
          </text>
          <path
            d={series.points
              .map(
                (point, index) =>
                  `${index === 0 ? 'M' : 'L'}${scale.x(point.timestamp).toFixed(2)} ${valueScale(
                    point.value,
                  ).toFixed(2)}`,
              )
              .join(' ')}
            fill="none"
            stroke="#0d9488"
            strokeWidth={1.4}
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity={0.85}
            pointerEvents="none"
          />
          {series.points
            .filter((_point, index) => index % Math.max(1, Math.ceil(series.points.length / 14)) === 0)
            .map((point) => (
              <circle
                key={`env-dot-${point.timestamp}`}
                cx={scale.x(point.timestamp)}
                cy={valueScale(point.value)}
                r={1.8}
                fill="#ffffff"
                stroke="#0d9488"
                strokeWidth={1}
                pointerEvents="none"
              />
            ))}
          <Mark
            id={`${series.id}-hit`}
            label={`${series.label} line, ${series.points.length} samples in ${series.unit}`}
            selected={false}
            onSelect={() =>
              onSelect({
                kind: 'series-point',
                laneId: lane.id,
                series,
                point: series.points[Math.floor(series.points.length / 2)],
              })
            }
          >
            <rect
              x={0}
              y={SERIES_TOP - 6}
              width={scale.width}
              height={seriesBottom - SERIES_TOP + 12}
              fill="transparent"
            />
          </Mark>
        </g>
      ) : null}
    </>
  );
}
