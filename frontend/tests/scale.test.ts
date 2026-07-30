import { describe, expect, it } from 'vitest';
import { PAD_LEFT, PAD_RIGHT, axisTicks, createScale, createValueScale } from '../src/timeline/scale';

const TZ = 'America/New_York';

describe('time-to-x scale', () => {
  it('maps the day onto the drawable width', () => {
    const scale = createScale(
      '2025-06-10T00:00:00-04:00',
      '2025-06-11T00:00:00-04:00',
      1000,
      TZ,
    );
    expect(scale.x('2025-06-10T00:00:00-04:00')).toBe(PAD_LEFT);
    expect(scale.x('2025-06-11T00:00:00-04:00')).toBe(1000 - PAD_RIGHT);
    expect(scale.x('2025-06-10T12:00:00-04:00')).toBeCloseTo(PAD_LEFT + (1000 - PAD_LEFT - PAD_RIGHT) / 2, 5);
  });

  it('clamps values outside the day', () => {
    const scale = createScale(
      '2025-06-10T00:00:00-04:00',
      '2025-06-11T00:00:00-04:00',
      1000,
      TZ,
    );
    expect(scale.fraction('2025-06-09T18:00:00-04:00')).toBe(0);
    expect(scale.fraction('2025-06-12T18:00:00-04:00')).toBe(1);
  });

  it('does not assume a 24-hour day on a spring-forward date', () => {
    // 2025-03-09 in New York is 23 hours long.
    const scale = createScale(
      '2025-03-09T00:00:00-05:00',
      '2025-03-10T00:00:00-04:00',
      1000,
      TZ,
    );
    const noon = '2025-03-09T12:00:00-04:00'; // 11 real hours after midnight
    expect(scale.fraction(noon)).toBeCloseTo(11 / 23, 5);
    expect(scale.fraction(noon)).toBeLessThan(0.5);
  });

  it('handles a 25-hour fall-back day', () => {
    const scale = createScale(
      '2025-11-02T00:00:00-04:00',
      '2025-11-03T00:00:00-05:00',
      1000,
      TZ,
    );
    expect(scale.fraction('2025-11-02T12:00:00-05:00')).toBeCloseTo(13 / 25, 5);
  });

  it('round-trips x back to a time', () => {
    const scale = createScale(
      '2025-06-10T00:00:00-04:00',
      '2025-06-11T00:00:00-04:00',
      1000,
      TZ,
    );
    const moment = new Date('2025-06-10T15:20:00-04:00');
    const back = scale.timeAt(scale.x(moment));
    expect(Math.abs(back.getTime() - moment.getTime())).toBeLessThan(120_000);
  });
});

describe('axis ticks', () => {
  it('labels every three hours plus the closing midnight', () => {
    const scale = createScale(
      '2025-06-10T00:00:00-04:00',
      '2025-06-11T00:00:00-04:00',
      1000,
      TZ,
    );
    expect(axisTicks(scale).map((tick) => tick.label)).toEqual([
      '12 AM',
      '3 AM',
      '6 AM',
      '9 AM',
      '12 PM',
      '3 PM',
      '6 PM',
      '9 PM',
      '12 AM',
    ]);
  });

  it('keeps ticks in ascending x order', () => {
    const scale = createScale(
      '2025-06-10T00:00:00-04:00',
      '2025-06-11T00:00:00-04:00',
      1000,
      TZ,
    );
    const xs = axisTicks(scale).map((tick) => tick.x);
    expect([...xs].sort((a, b) => a - b)).toEqual(xs);
  });

  it('drops the skipped hour on a spring-forward day', () => {
    const scale = createScale(
      '2025-03-09T00:00:00-05:00',
      '2025-03-10T00:00:00-04:00',
      1000,
      TZ,
    );
    // 2 AM does not exist; 3 AM does, and the day still closes at midnight.
    const labels = axisTicks(scale).map((tick) => tick.label);
    expect(labels[0]).toBe('12 AM');
    expect(labels.at(-1)).toBe('12 AM');
    expect(new Set(labels).size).toBeGreaterThan(4);
  });
});

describe('value scale', () => {
  it('puts the largest value nearest the top of the lane', () => {
    const toY = createValueScale([10, 20, 30], 10, 90);
    expect(toY(30)).toBeLessThan(toY(10));
    expect(toY(30)).toBeGreaterThanOrEqual(10);
    expect(toY(10)).toBeLessThanOrEqual(90);
  });

  it('does not divide by zero for a flat series', () => {
    const toY = createValueScale([42, 42, 42], 0, 100);
    expect(Number.isFinite(toY(42))).toBe(true);
  });

  it('honours an explicit scale such as a 0-100 score', () => {
    const toY = createValueScale([70, 80], 0, 100, 0, 100);
    expect(toY(80)).toBeLessThan(toY(70));
  });
});
