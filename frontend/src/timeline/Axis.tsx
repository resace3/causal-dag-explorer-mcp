import { AXIS_HEIGHT, GRID_LINE, GRID_LINE_MINOR } from '../utilities/lanes';
import { axisTicks, minorTickPositions, type DayScale } from './scale';

export function AxisRow({ scale, position }: { scale: DayScale; position: 'top' | 'bottom' }) {
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
    </svg>
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
