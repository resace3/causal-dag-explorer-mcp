/**
 * The collapsed view's date window: a month either side of the chosen day.
 */

import { describe, expect, it } from 'vitest';
import { datesAround } from '../src/hooks/useDayRange';

describe('datesAround', () => {
  it('centres the window on the chosen day', () => {
    const dates = datesAround('2026-07-15', 30, 30);
    expect(dates).toHaveLength(61);
    expect(dates[30]).toBe('2026-07-15');
    expect(dates[0]).toBe('2026-06-15');
    expect(dates.at(-1)).toBe('2026-08-14');
  });

  it('returns dates in order with no gaps', () => {
    const dates = datesAround('2026-03-15', 5, 5);
    for (let index = 1; index < dates.length; index += 1) {
      const previous = new Date(`${dates[index - 1]}T12:00:00Z`);
      previous.setUTCDate(previous.getUTCDate() + 1);
      expect(dates[index]).toBe(previous.toISOString().slice(0, 10));
    }
  });

  it('stops at today, because a day that has not happened holds no data', () => {
    const dates = datesAround('2026-07-29', 30, 30, '2026-07-30');
    expect(dates.at(-1)).toBe('2026-07-30');
    expect(dates).toContain('2026-07-29');
    expect(dates.some((date) => date > '2026-07-30')).toBe(false);
  });

  it('still reaches a full month back when the forward end is clamped', () => {
    const dates = datesAround('2026-07-30', 30, 30, '2026-07-30');
    expect(dates[0]).toBe('2026-06-30');
    expect(dates.at(-1)).toBe('2026-07-30');
  });

  it('crosses a month boundary correctly', () => {
    const dates = datesAround('2026-03-02', 3, 3);
    expect(dates).toEqual([
      '2026-02-27',
      '2026-02-28',
      '2026-03-01',
      '2026-03-02',
      '2026-03-03',
      '2026-03-04',
      '2026-03-05',
    ]);
  });

  it('crosses a year boundary correctly', () => {
    const dates = datesAround('2026-01-01', 2, 1);
    expect(dates).toEqual(['2025-12-30', '2025-12-31', '2026-01-01', '2026-01-02']);
  });

  it('handles a leap day', () => {
    expect(datesAround('2028-02-29', 1, 1)).toEqual([
      '2028-02-28',
      '2028-02-29',
      '2028-03-01',
    ]);
  });
});
