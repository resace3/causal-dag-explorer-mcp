import type { ReactNode } from 'react';
import type { DayScale } from '../timeline/scale';
import type { Lane, Selection, TimelineEvent } from '../types/timeline';
import { formatDuration, formatTime, formatTimeRange } from '../utilities/time';
import { MISSING_FILL, MISSING_STROKE } from '../utilities/lanes';

export interface LaneRenderProps {
  lane: Lane;
  scale: DayScale;
  height: number;
  timeZone: string;
  selectedKey: string | null;
  onSelect: (selection: Selection) => void;
}

/** Screen-reader sentence for one event. Colour is never the only signal. */
export function describeEvent(event: TimelineEvent, timeZone: string): string {
  const parts = [event.label, formatTimeRange(event.startTime, event.endTime, timeZone)];
  const minutes = event.metadata?.durationMinutes;
  if (typeof minutes === 'number') parts.push(`duration ${formatDuration(minutes)}`);
  if (event.value != null) parts.push(`value ${event.value}${event.unit ? ` ${event.unit}` : ''}`);
  parts.push(`source ${event.device ?? event.source}`);
  parts.push(event.measuredOrDerived === 'derived' ? 'derived feature' : 'measured');
  if (event.continuesBefore) parts.push('continues from the previous day');
  if (event.continuesAfter) parts.push('continues into the next day');
  return `${parts.join(', ')}.`;
}

interface MarkProps {
  id: string;
  label: string;
  selected: boolean;
  onSelect: () => void;
  children: ReactNode;
  className?: string;
}

/** A keyboard-reachable, screen-reader-labelled timeline mark. */
export function Mark({ id, label, selected, onSelect, children, className }: MarkProps) {
  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={label}
      aria-pressed={selected}
      data-mark-id={id}
      data-selected={selected ? 'true' : undefined}
      className={`tl-mark${className ? ` ${className}` : ''}`}
      onClick={(clickEvent) => {
        clickEvent.stopPropagation();
        onSelect();
      }}
      onKeyDown={(keyEvent) => {
        if (keyEvent.key === 'Enter' || keyEvent.key === ' ') {
          keyEvent.preventDefault();
          keyEvent.stopPropagation();
          onSelect();
        }
      }}
    >
      {children}
    </g>
  );
}

/** Diagonal hatch used for every missing-data region, in every lane. */
export function MissingDataDefs({ id }: { id: string }) {
  return (
    <defs>
      <pattern id={id} width="7" height="7" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
        <rect width="7" height="7" fill={MISSING_FILL} />
        <line x1="0" y1="0" x2="0" y2="7" stroke={MISSING_STROKE} strokeWidth="1.4" />
      </pattern>
    </defs>
  );
}

/**
 * A rounded interval bar that squares off the edge it runs past, and marks the
 * clipped side with a chevron so a continuation is never mistaken for an end.
 */
export function IntervalBar({
  x,
  width,
  y,
  height,
  fill,
  opacity = 1,
  continuesBefore,
  continuesAfter,
  stroke,
}: {
  x: number;
  width: number;
  y: number;
  height: number;
  fill: string;
  opacity?: number;
  continuesBefore?: boolean;
  continuesAfter?: boolean;
  stroke?: string;
}) {
  const radius = Math.min(height / 2, 8);
  const safeWidth = Math.max(width, 2.5);
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={safeWidth}
        height={height}
        rx={radius}
        ry={radius}
        fill={fill}
        opacity={opacity}
        stroke={stroke}
        strokeWidth={stroke ? 1 : 0}
      />
      {continuesBefore ? (
        <>
          <rect x={x} y={y} width={radius} height={height} fill={fill} opacity={opacity} />
          <path
            d={`M${x + 4.5} ${y + 1} L${x + 0.5} ${y + height / 2} L${x + 4.5} ${y + height - 1}`}
            fill="none"
            stroke="#ffffff"
            strokeWidth={1.4}
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity={0.9}
          />
        </>
      ) : null}
      {continuesAfter ? (
        <>
          <rect
            x={x + safeWidth - radius}
            y={y}
            width={radius}
            height={height}
            fill={fill}
            opacity={opacity}
          />
          <path
            d={`M${x + safeWidth - 4.5} ${y + 1} L${x + safeWidth - 0.5} ${y + height / 2} L${
              x + safeWidth - 4.5
            } ${y + height - 1}`}
            fill="none"
            stroke="#ffffff"
            strokeWidth={1.4}
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity={0.9}
          />
        </>
      ) : null}
    </g>
  );
}

const CHAR_WIDTH = 0.56;

export function approximateTextWidth(text: string, fontSize: number): number {
  return text.length * fontSize * CHAR_WIDTH;
}

export interface PlacedLabel {
  x: number;
  anchor: 'start' | 'end';
  visible: boolean;
}

/**
 * Greedy label placement.
 *
 * A label is tried to the right of its node, then to the left, and is dropped
 * if neither side is clear. `reserved` holds the node circles themselves, so a
 * label never runs across a neighbouring marker — the collision that made two
 * nearby events unreadable. Hidden labels are still reachable through the
 * tooltip and the details panel, so only the clutter is lost.
 */
export function placeLabels(
  anchors: { x: number; width: number; offset?: number }[],
  scale: DayScale,
  gap = 10,
  /** Node boxes, parallel to `anchors`. A label ignores its *own* node. */
  nodeBoxes: [number, number][] = [],
): PlacedLabel[] {
  const placed: [number, number][] = [];
  const right = scale.width - 6;

  const fits = (box: [number, number], ownIndex: number) => {
    if (box[0] < 2 || box[1] > right) return false;
    const overlaps = ([low, high]: [number, number]) => box[0] < high && box[1] > low;
    if (placed.some(overlaps)) return false;
    return !nodeBoxes.some((node, index) => index !== ownIndex && overlaps(node));
  };

  return anchors.map(({ x, width, offset = 0 }, index) => {
    const rightStart = x + offset;
    const rightBox: [number, number] = [rightStart - gap, rightStart + width + gap];
    if (fits(rightBox, index)) {
      placed.push(rightBox);
      return { x: rightStart, anchor: 'start', visible: true };
    }

    const leftEnd = x - offset;
    const leftBox: [number, number] = [leftEnd - width - gap, leftEnd + gap];
    if (fits(leftBox, index)) {
      placed.push(leftBox);
      return { x: leftEnd, anchor: 'end', visible: true };
    }

    return { x: rightStart, anchor: 'start', visible: false };
  });
}

export function laneAriaLabel(lane: Lane): string {
  const bits = [`${lane.label} lane`, lane.description];
  if (lane.events.length) bits.push(`${lane.events.length} events`);
  if (lane.series.length) {
    bits.push(
      `${lane.series.length} continuous series with ${lane.series.reduce(
        (total, series) => total + series.points.length,
        0,
      )} samples`,
    );
  }
  return bits.join(', ');
}

export function eventTooltip(event: TimelineEvent, timeZone: string): string {
  const lines = [event.label, formatTimeRange(event.startTime, event.endTime, timeZone)];
  if (event.value != null) lines.push(`${event.value}${event.unit ? ` ${event.unit}` : ''}`);
  lines.push(event.measuredOrDerived === 'derived' ? 'Derived feature' : 'Measured');
  return lines.join('\n');
}

export function shortTime(value: string, timeZone: string): string {
  return formatTime(value, timeZone).replace(':00', '');
}
