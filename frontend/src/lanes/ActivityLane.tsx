/**
 * Activity lane.
 *
 * Discrete sessions are the thing worth reading, so they keep the node, label
 * and duration bar. A step-rate line, when a counter is available, is drawn
 * behind them as context — it shows *when* movement happened without competing
 * with the named sessions.
 */

import { useMemo } from 'react';
import { createValueScale } from '../timeline/scale';
import { accentTheme } from '../utilities/lanes';
import { toDate } from '../utilities/time';
import { EventLane } from './EventLane';
import { MissingDataDefs, type LaneRenderProps } from './shared';

const SPARK_TOP_RATIO = 0.52;

export function ActivityLane(props: LaneRenderProps) {
  const { lane, scale, height } = props;
  const theme = accentTheme(lane.accent);
  const series = lane.series[0];
  const patternId = `missing-${lane.id}-spark`;

  const top = Math.round(height * SPARK_TOP_RATIO);
  const bottom = height - 8;

  const valueScale = useMemo(
    () =>
      series
        ? createValueScale(
            series.points.map((point) => point.value),
            top,
            bottom,
          )
        : null,
    [series, top, bottom],
  );

  const segments = useMemo(() => {
    if (!series) return [];
    const gaps = series.gaps.map((gap) => ({
      start: toDate(gap.startTime).getTime(),
      end: toDate(gap.endTime).getTime(),
    }));
    const result: (typeof series.points)[] = [[]];
    let previous: number | null = null;
    for (const point of series.points) {
      const time = toDate(point.timestamp).getTime();
      const crossesGap =
        previous !== null &&
        gaps.some((gap) => gap.start >= previous! && gap.end <= time && gap.end > gap.start);
      if (crossesGap) result.push([]);
      result[result.length - 1].push(point);
      previous = time;
    }
    return result.filter((segment) => segment.length > 0);
  }, [series]);

  return (
    <>
      {series && valueScale ? (
        <g pointerEvents="none">
          <MissingDataDefs id={patternId} />
          {series.gaps.map((gap, index) => {
            const x = scale.x(gap.startTime);
            const width = Math.max(scale.x(gap.endTime) - x, 1);
            if (width < 3) return null;
            return (
              <rect
                key={`spark-gap-${index}`}
                x={x}
                y={top - 3}
                width={width}
                height={bottom - top + 6}
                fill={`url(#${patternId})`}
                opacity={0.6}
              />
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
            const area = `${path} L${scale
              .x(segment[segment.length - 1].timestamp)
              .toFixed(2)} ${bottom} L${scale.x(segment[0].timestamp).toFixed(2)} ${bottom} Z`;
            return (
              <g key={`spark-${index}`}>
                <path d={area} fill={theme.stroke} opacity={0.09} />
                <path
                  d={path}
                  fill="none"
                  stroke={theme.stroke}
                  strokeWidth={1.3}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  opacity={0.65}
                />
              </g>
            );
          })}
          <text x={6} y={top - 6} fontSize={9.5} fill={theme.text} opacity={0.85}>
            {series.label} ({series.unit})
          </text>
        </g>
      ) : null}

      <EventLane {...props} lane={{ ...lane, series: [] }} />
    </>
  );
}
