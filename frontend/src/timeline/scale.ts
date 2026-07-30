/**
 * The shared time-to-x mapping. Every lane uses this one function, which is
 * what keeps the swimlanes aligned.
 *
 *   x = padLeft + fractionOfDay * drawableWidth
 *
 * `fractionOfDay` divides by the day's real length, so 23- and 25-hour
 * daylight-saving days scale correctly instead of being assumed to be 24 hours.
 */

import { toDate, wallClock } from '../utilities/time';

export const PAD_LEFT = 26;
export const PAD_RIGHT = 26;

export interface AxisTick {
  time: Date;
  x: number;
  label: string;
  major: boolean;
}

export interface DayScale {
  dayStart: Date;
  dayEnd: Date;
  width: number;
  drawableWidth: number;
  timeZone: string;
  fraction(value: Date | string): number;
  x(value: Date | string): number;
  timeAt(x: number): Date;
  clamp(x: number): number;
}

export function createScale(
  dayStart: string | Date,
  dayEnd: string | Date,
  width: number,
  timeZone: string,
): DayScale {
  const start = toDate(dayStart);
  const end = toDate(dayEnd);
  const spanMs = Math.max(1, end.getTime() - start.getTime());
  const drawableWidth = Math.max(1, width - PAD_LEFT - PAD_RIGHT);

  const fraction = (value: Date | string) => {
    const offset = toDate(value).getTime() - start.getTime();
    return Math.min(1, Math.max(0, offset / spanMs));
  };

  return {
    dayStart: start,
    dayEnd: end,
    width,
    drawableWidth,
    timeZone,
    fraction,
    x: (value) => PAD_LEFT + fraction(value) * drawableWidth,
    timeAt: (x) => {
      const ratio = Math.min(1, Math.max(0, (x - PAD_LEFT) / drawableWidth));
      return new Date(start.getTime() + ratio * spanMs);
    },
    clamp: (x) => Math.min(PAD_LEFT + drawableWidth, Math.max(PAD_LEFT, x)),
  };
}

function formatHourLabel(hour: number): string {
  if (hour === 0 || hour === 24) return '12 AM';
  if (hour === 12) return '12 PM';
  return hour < 12 ? `${hour} AM` : `${hour - 12} PM`;
}

/**
 * Ticks at every `stepHours` local wall-clock hour that actually exists in the
 * day, plus the closing midnight. Scanning real time rather than assuming 24
 * slots keeps the labels honest across daylight-saving transitions.
 */
export function axisTicks(scale: DayScale, stepHours = 3): AxisTick[] {
  const ticks: AxisTick[] = [];
  const seen = new Set<number>();
  const hourMs = 3_600_000;
  const total = scale.dayEnd.getTime() - scale.dayStart.getTime();
  const steps = Math.ceil(total / hourMs) + 1;

  for (let index = 0; index <= steps; index += 1) {
    const time = new Date(scale.dayStart.getTime() + index * hourMs);
    if (time > scale.dayEnd) break;
    const { hour, minute } = wallClock(time, scale.timeZone);
    if (minute !== 0 || hour % stepHours !== 0) continue;
    const x = Math.round(scale.x(time));
    if (seen.has(x)) continue;
    seen.add(x);
    ticks.push({ time, x, label: formatHourLabel(hour), major: true });
  }

  const endX = Math.round(scale.x(scale.dayEnd));
  if (!seen.has(endX)) {
    ticks.push({ time: scale.dayEnd, x: endX, label: '12 AM', major: true });
  }
  return ticks;
}

/** Faint one-hour lines between the labelled ticks. */
export function minorTickPositions(scale: DayScale): number[] {
  const positions: number[] = [];
  const hourMs = 3_600_000;
  const steps = Math.ceil((scale.dayEnd.getTime() - scale.dayStart.getTime()) / hourMs);
  for (let index = 1; index < steps; index += 1) {
    const time = new Date(scale.dayStart.getTime() + index * hourMs);
    const { hour, minute } = wallClock(time, scale.timeZone);
    if (minute === 0 && hour % 3 === 0) continue;
    positions.push(scale.x(time));
  }
  return positions;
}

/** Linear value-to-y mapping inside a lane, with a little headroom. */
export function createValueScale(
  values: number[],
  top: number,
  bottom: number,
  explicitMin?: number | null,
  explicitMax?: number | null,
): (value: number) => number {
  const numbers = values.filter((value) => Number.isFinite(value));
  let min = explicitMin ?? (numbers.length ? Math.min(...numbers) : 0);
  let max = explicitMax ?? (numbers.length ? Math.max(...numbers) : 1);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const padding = (max - min) * 0.14;
  min -= padding;
  max += padding;
  const height = bottom - top;
  return (value: number) => bottom - ((value - min) / (max - min)) * height;
}
