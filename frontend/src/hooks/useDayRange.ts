/**
 * Load a run of consecutive days for the collapsed view.
 *
 * Only days the server has already processed are fetched automatically.
 * Requesting an unprocessed day makes the backend go out to Home Assistant and
 * the wearable MCP and rebuild it, which can take the better part of a minute —
 * so widening the window must never silently kick off five of those. An
 * unfetched day is reported as such and loaded only when explicitly asked for.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { DayTimeline } from '../types/timeline';

export type DayStatus = 'loaded' | 'loading' | 'unfetched' | 'error';

export interface RangeDay {
  date: string;
  timeline: DayTimeline | null;
  status: DayStatus;
  error?: string;
}

/** `count` consecutive dates ending at `endDate`, oldest first. */
export function datesEndingAt(endDate: string, count: number): string[] {
  const dates: string[] = [];
  const end = new Date(`${endDate}T12:00:00Z`);
  for (let offset = count - 1; offset >= 0; offset -= 1) {
    const day = new Date(end);
    day.setUTCDate(day.getUTCDate() - offset);
    dates.push(day.toISOString().slice(0, 10));
  }
  return dates;
}

export function useDayRange(dates: string[], storedDates: Set<string>) {
  const [days, setDays] = useState<Record<string, RangeDay>>({});
  const cache = useRef<Map<string, DayTimeline>>(new Map());
  const inFlight = useRef<Set<string>>(new Set());
  const key = dates.join(',');

  const fetchDay = useCallback((date: string) => {
    if (inFlight.current.has(date)) return;
    inFlight.current.add(date);
    setDays((current) => ({
      ...current,
      [date]: { date, timeline: current[date]?.timeline ?? null, status: 'loading' },
    }));
    void api
      .day(date)
      .then((timeline) => {
        cache.current.set(date, timeline);
        setDays((current) => ({ ...current, [date]: { date, timeline, status: 'loaded' } }));
      })
      .catch((cause) => {
        setDays((current) => ({
          ...current,
          [date]: {
            date,
            timeline: null,
            status: 'error',
            error: cause instanceof Error ? cause.message : String(cause),
          },
        }));
      })
      .finally(() => {
        inFlight.current.delete(date);
      });
  }, []);

  useEffect(() => {
    for (const date of key.split(',').filter(Boolean)) {
      if (cache.current.has(date)) {
        const timeline = cache.current.get(date)!;
        setDays((current) =>
          current[date]?.status === 'loaded'
            ? current
            : { ...current, [date]: { date, timeline, status: 'loaded' } },
        );
        continue;
      }
      if (storedDates.has(date)) {
        fetchDay(date);
      } else {
        setDays((current) =>
          current[date]
            ? current
            : { ...current, [date]: { date, timeline: null, status: 'unfetched' } },
        );
      }
    }
    // `storedDates` is rebuilt on every render of the caller, so keying the
    // effect on its contents rather than its identity avoids a refetch loop.
  }, [key, [...storedDates].sort().join(','), fetchDay]);

  const ordered: RangeDay[] = dates.map(
    (date) => days[date] ?? { date, timeline: null, status: 'unfetched' },
  );

  return { days: ordered, load: fetchDay };
}
