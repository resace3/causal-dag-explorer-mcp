import { AXIS_HEIGHT, GRID_LINE, GRID_LINE_MINOR, NOW_LINE } from '../utilities/lanes';
import { axisTicks, minorTickPositions, type DayScale } from './scale';

export function AxisRow({
  scale,
  position,
  nowX = null,
}: {
  scale: DayScale;
  position: 'top' | 'bottom';
  /** x of the current time, or null on a day that does not contain one. */
  nowX?: number | null;
}) {
  const ticks = axisTicks(scale);
  const y = position === 'top' ? AXIS_HEIGHT - 10 : 18;

  return (
    <svg
      width={scale.width}
      height={AXIS_HEIGHT}
      className="block"
      role="presentation"
      aria-hidden="true"
    >
      {ticks.map((tick) => (
        <text
          key={`${position}-${tick.x}`}
          x={tick.x}
          y={y}
          textAnchor="middle"
          fontSize={11.5}
          fill="#64748b"
          fontWeight={500}
        >
          {tick.label}
        </text>
      ))}

      {/* The line runs through every lane; the axis gives it a name, once, so
          it does not read as a stray mark in one of them. */}
      {nowX !== null ? (
        <g pointerEvents="none">
          <line
            x1={nowX}
            x2={nowX}
            y1={position === 'top' ? AXIS_HEIGHT - 6 : 0}
            y2={position === 'top' ? AXIS_HEIGHT : 6}
            stroke={NOW_LINE}
            strokeWidth={1.5}
          />
          {position === 'top' ? (
            <text
              x={nowX}
              y={11}
              textAnchor="middle"
              fontSize={9.5}
              fontWeight={600}
              fill={NOW_LINE}
            >
              Now
            </text>
          ) : null}
        </g>
      ) : null}
    </svg>
  );
}

/**
 * The current-time line, drawn inside a lane.
 *
 * Rendered after the lane's own marks rather than with the grid, because a wide
 * interval bar would otherwise cover it — and a "now" line you cannot see
 * during the very session you are looking at is the case it exists for.
 */
export function NowLine({ x, height }: { x: number; height: number }) {
  return (
    <line
      x1={x}
      x2={x}
      y1={0}
      y2={height}
      stroke={NOW_LINE}
      strokeWidth={1.5}
      pointerEvents="none"
      data-testid="now-line"
    />
  );
}

/** Shared vertical grid, drawn identically inside every lane. */
export function GridLines({ scale, height }: { scale: DayScale; height: number }) {
  const ticks = axisTicks(scale);
  const minor = minorTickPositions(scale);

  return (
    <g pointerEvents="none">
      {minor.map((x) => (
        <line
          key={`minor-${x}`}
          x1={x}
          x2={x}
          y1={0}
          y2={height}
          stroke={GRID_LINE_MINOR}
          strokeWidth={1}
        />
      ))}
      {ticks.map((tick) => (
        <line
          key={`major-${tick.x}`}
          x1={tick.x}
          x2={tick.x}
          y1={0}
          y2={height}
          stroke={GRID_LINE}
          strokeWidth={1}
        />
      ))}
    </g>
  );
}
