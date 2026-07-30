/**
 * Lanes carrying a continuous measurement: Heart Rate, Readiness, Temperature,
 * and the step-rate line derived from a cumulative counter.
 *
 * Lines break across declared gaps rather than interpolating over them, and
 * every sample is selectable — by pointer, or with the arrow keys once the line
 * has focus.
 */

import { useMemo, useRef, useState } from 'react';
import type { DayScale } from '../timeline/scale';
import { createValueScale } from '../timeline/scale';
import type { Lane, Selection, SeriesPoint, TimelineEvent, TimelineSeries } from '../types/timeline';
import { accentTheme } from '../utilities/lanes';
import { formatTime, formatTimeRange, toDate } from '../utilities/time';
import {
  Mark,
  MissingDataDefs,
  describeEvent,
  eventTooltip,
  type LaneRenderProps,
} from './shared';

const TOP_INSET = 18;
const BOTTOM_INSET = 20;

function segmentPoints(series: TimelineSeries): SeriesPoint[][] {
  if (!series.points.length) return [];
  const gaps = series.gaps.map((gap) => ({
    start: toDate(gap.startTime).getTime(),
    end: toDate(gap.endTime).getTime(),
  }));

  const segments: SeriesPoint[][] = [[]];
  let previous: number | null = null;
  for (const point of series.points) {
    const time = toDate(point.timestamp).getTime();
    const crossesGap =
      previous !== null &&
      gaps.some((gap) => gap.start >= previous! && gap.end <= time && gap.end > gap.start);
    if (crossesGap) segments.push([]);
    segments[segments.length - 1].push(point);
    previous = time;
  }
  return segments.filter((segment) => segment.length > 0);
}

function nearestIndex(series: TimelineSeries, time: number): number {
  let best = 0;
  let bestDelta = Number.POSITIVE_INFINITY;
  series.points.forEach((point, index) => {
    const delta = Math.abs(toDate(point.timestamp).getTime() - time);
    if (delta < bestDelta) {
      bestDelta = delta;
      best = index;
    }
  });
  return best;
}

function formatValue(value: number, unit: string): string {
  const decimals = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
  return `${value.toFixed(decimals)}${unit && unit.length <= 4 ? ` ${unit}` : ''}`;
}

interface SeriesLayerProps {
  lane: Lane;
  series: TimelineSeries;
  scale: DayScale;
  height: number;
  timeZone: string;
  selectedKey: string | null;
  onSelect: (selection: Selection) => void;
  events: TimelineEvent[];
}

function SeriesLayer({
  lane,
  series,
  scale,
  height,
  timeZone,
  selectedKey,
  onSelect,
  events,
}: SeriesLayerProps) {
  const theme = accentTheme(lane.accent);
  const secondary = series.style === 'secondary';
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [focusIndex, setFocusIndex] = useState(0);
  const overlayRef = useRef<SVGRectElement | null>(null);
  const patternId = `missing-${lane.id}-${series.id}`;

  const top = TOP_INSET;
  const bottom = height - BOTTOM_INSET;

  const valueScale = useMemo(
    () =>
      createValueScale(
        series.points.map((point) => point.value),
        top,
        bottom,
        series.metadata?.scaleMin as number | undefined,
        series.metadata?.scaleMax as number | undefined,
      ),
    [series, top, bottom],
  );

  const segments = useMemo(() => segmentPoints(series), [series]);
  const extremes = useMemo(() => {
    if (!series.points.length) return null;
    let min = series.points[0];
    let max = series.points[0];
    for (const point of series.points) {
      if (point.value < min.value) min = point;
      if (point.value > max.value) max = point;
    }
    return { min, max };
  }, [series]);

  const dotStep = Math.max(1, Math.ceil(series.points.length / 26));

  const select = (index: number) => {
    const point = series.points[index];
    if (!point) return;
    onSelect({ kind: 'series-point', laneId: lane.id, series, point });
  };

  const handleMove = (clientX: number) => {
    const rect = overlayRef.current?.getBoundingClientRect();
    if (!rect) return;
    const time = scale.timeAt(clientX - rect.left).getTime();
    setHoverIndex(nearestIndex(series, time));
  };

  const activePoint = hoverIndex != null ? series.points[hoverIndex] : null;

  return (
    <g>
      <MissingDataDefs id={patternId} />

      {/*
        The line's hit target is painted FIRST so it sits under the event marks.
        SVG paints in document order, so an overlay drawn last would swallow
        every click meant for an interval band or a node.
      */}
      <rect
        ref={overlayRef}
        x={0}
        y={0}
        width={scale.width}
        height={height}
        fill="transparent"
        role="button"
        tabIndex={0}
        aria-label={`${series.label} line, ${series.points.length} samples in ${series.unit}. Use the arrow keys to move between samples.`}
        onMouseMove={(moveEvent) => handleMove(moveEvent.clientX)}
        onMouseLeave={() => setHoverIndex(null)}
        onClick={() => {
          if (hoverIndex != null) select(hoverIndex);
        }}
        onFocus={() => setHoverIndex(focusIndex)}
        onBlur={() => setHoverIndex(null)}
        onKeyDown={(keyEvent) => {
          if (keyEvent.key === 'ArrowRight' || keyEvent.key === 'ArrowLeft') {
            keyEvent.preventDefault();
            const step = keyEvent.key === 'ArrowRight' ? 1 : -1;
            const next = Math.min(
              series.points.length - 1,
              Math.max(0, (hoverIndex ?? focusIndex) + step),
            );
            setFocusIndex(next);
            setHoverIndex(next);
          } else if (keyEvent.key === 'Enter' || keyEvent.key === ' ') {
            keyEvent.preventDefault();
            select(hoverIndex ?? focusIndex);
          }
        }}
      >
        <title>
          {activePoint
            ? `${series.label}: ${formatValue(activePoint.value, series.unit)} at ${formatTime(
                activePoint.timestamp,
                timeZone,
              )}`
            : series.label}
        </title>
      </rect>

      {series.gaps.map((gap, index) => {
        const x = scale.x(gap.startTime);
        const width = Math.max(scale.x(gap.endTime) - x, 1);
        if (width < 3) return null;
        return (
          <g key={`gap-${index}`} pointerEvents="none">
            <rect
              x={x}
              y={top - 4}
              width={width}
              height={bottom - top + 8}
              fill={`url(#${patternId})`}
              opacity={0.75}
            />
            {width > 74 ? (
              <text
                x={x + width / 2}
                y={(top + bottom) / 2 + 4}
                textAnchor="middle"
                fontSize={10}
                fill="#7c8a9c"
              >
                No data
              </text>
            ) : null}
          </g>
        );
      })}

      {events
        .filter((event) => event.eventType === 'interval')
        .map((event) => {
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
                y={top - 6}
                width={width}
                height={bottom - top + 12}
                fill={theme.soft}
                opacity={selected ? 0.85 : 0.5}
                rx={4}
              />
              <rect
                x={x}
                y={bottom + 5}
                width={width}
                height={selected ? 4.5 : 3}
                rx={2}
                fill={theme.fill}
              />
            </Mark>
          );
        })}

      {segments.map((segment, index) => {
        const path = segment
          .map(
            (point, pointIndex) =>
              `${pointIndex === 0 ? 'M' : 'L'}${scale.x(point.timestamp).toFixed(2)} ${valueScale(
                point.value,
              ).toFixed(2)}`,
          )
          .join(' ');
        const area = `${path} L${scale.x(segment[segment.length - 1].timestamp).toFixed(
          2,
        )} ${bottom} L${scale.x(segment[0].timestamp).toFixed(2)} ${bottom} Z`;
        return (
          <g key={`segment-${index}`} pointerEvents="none">
            {!secondary ? <path d={area} fill={theme.stroke} opacity={0.07} /> : null}
            <path
              d={path}
              fill="none"
              stroke={theme.stroke}
              strokeWidth={secondary ? 1.3 : 1.9}
              strokeDasharray={secondary ? '4 3' : undefined}
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity={secondary ? 0.75 : 1}
            />
          </g>
        );
      })}

      <g pointerEvents="none">
        {series.points
          .filter((_point, index) => index % dotStep === 0)
          .map((point) => (
            <circle
              key={`dot-${point.timestamp}`}
              cx={scale.x(point.timestamp)}
              cy={valueScale(point.value)}
              r={secondary ? 1.8 : 2.6}
              fill="#ffffff"
              stroke={theme.stroke}
              strokeWidth={1.2}
            />
          ))}

        {extremes && !secondary
          ? (extremes.min === extremes.max
              ? // One reading, or a flat line: label it once.
                [{ point: extremes.max, dy: -9 }]
              : [
                  { point: extremes.max, dy: -9 },
                  { point: extremes.min, dy: 16 },
                ]
            ).map(({ point, dy }) => (
              <text
                key={`extreme-${point.timestamp}-${dy}`}
                x={scale.x(point.timestamp)}
                y={valueScale(point.value) + dy}
                textAnchor="middle"
                fontSize={10}
                fill={theme.text}
                fontWeight={600}
                stroke="#ffffff"
                strokeWidth={2.6}
                paintOrder="stroke"
              >
                {formatValue(point.value, series.unit)}
              </text>
            ))
          : null}
      </g>

      {events
        .filter((event) => event.eventType === 'point')
        .map((event) => {
          const index = nearestIndex(series, toDate(event.startTime).getTime());
          const point = series.points[index];
          if (!point) return null;
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
              <circle
                cx={scale.x(event.startTime)}
                cy={valueScale(point.value)}
                r={selected ? 7 : 5.6}
                fill="#ffffff"
                stroke={theme.stroke}
                strokeWidth={selected ? 2.6 : 2}
              />
            </Mark>
          );
        })}

      {activePoint ? (
        <g pointerEvents="none">
          <line
            x1={scale.x(activePoint.timestamp)}
            x2={scale.x(activePoint.timestamp)}
            y1={top - 6}
            y2={bottom + 6}
            stroke={theme.stroke}
            strokeWidth={1}
            opacity={0.35}
          />
          <circle
            cx={scale.x(activePoint.timestamp)}
            cy={valueScale(activePoint.value)}
            r={4.4}
            fill={theme.stroke}
          />
        </g>
      ) : null}
    </g>
  );
}

export function ContinuousLane(props: LaneRenderProps) {
  const { lane, height, timeZone } = props;
  const theme = accentTheme(lane.accent);
  const primary = lane.series.filter((series) => series.style !== 'secondary');
  const secondary = lane.series.filter((series) => series.style === 'secondary');

  return (
    <>
      {[...secondary, ...primary].map((series) => (
        <SeriesLayer
          key={series.id}
          {...props}
          series={series}
          events={series.style === 'secondary' ? [] : lane.events}
        />
      ))}
      {lane.series.length ? (
        <text x={6} y={13} fontSize={10} fill={theme.text} opacity={0.9} pointerEvents="none">
          {lane.series.map((series) => `${series.label} (${series.unit})`).join(' · ')}
        </text>
      ) : null}
      {!lane.series.length && lane.events.length ? (
        <text x={6} y={height / 2} fontSize={11} fill="#64748b" pointerEvents="none">
          {formatTimeRange(lane.events[0].startTime, lane.events[0].endTime, timeZone)}
        </text>
      ) : null}
    </>
  );
}
