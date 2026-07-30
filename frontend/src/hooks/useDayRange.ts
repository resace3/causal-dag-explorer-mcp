/**
 * Load a run of consecutive days for the collapsed view.
 *
 * Nothing is fetched on its own. The window spans two months, and pulling every
 * stored day in it up front would fire dozens of requests for panels scrolled
 * far off screen; the collapsed view asks for a day only as its panel comes
 * into view. A day the server has never processed is never fetched
 * automatically at all, because reconstructing one goes out to Home Assistant
 * and the wearable MCP and takes the better part of a minute — that stays an
 * explicit choice.
 */

import { useCallback, useRef, useState } from 'react';
import { api } from '../api/client';
import type { DayTimeline } from '../types/timeline';

export type DayStatus = 'loaded' | 'loading' | 'unfetched' | 'error';

export interface RangeDay {
  date: string;
  timeline: DayTimeline | null;
  status: DayStatus;
  /** Whether the server already holds a processed timeline for this day. */
  stored: boolean;
  error?: string;
}

/**
 * `before` days back and `after` days forward from `centre`, oldest first.
 *
 * `latest` clamps the forward end. Days that have not happened yet hold no
 * data and cannot be reconstructed, so offering them would be offering nothing.
 */
export function datesAround(
  centre: string,
  before: number,
  after: number,
  latest?: string | null,
): string[] {
  const dates: string[] = [];
  const middle = new Date(`${centre}T12:00:00Z`);
  for (let offset = -before; offset <= after; offset += 1) {
    const day = new Date(middle);
    day.setUTCDate(day.getUTCDate() + offset);
    const iso = day.toISOString().slice(0, 10);
    if (latest && iso > latest) break;
    dates.push(iso);
  }
  return dates;
}

export function useDayRange(dates: string[], storedDates: Set<string>) {
  const [days, setDays] = useState<Record<string, RangeDay>>({});
  const inFlight = useRef<Set<string>>(new Set());

  const load = useCallback((date: string) => {
    if (inFlight.current.has(date)) return;
    inFlight.current.add(date);
    setDays((current) => {
      if (current[date]?.status === 'loaded') return current;
      return {
        ...current,
        [date]: {
          date,
          timeline: current[date]?.timeline ?? null,
          status: 'loading',
          stored: current[date]?.stored ?? false,
        },
      };
    });

    void api
      .day(date)
      .then((timeline) => {
        setDays((current) => ({
          ...current,
          [date]: { date, timeline, status: 'loaded', stored: true },
        }));
      })
      .catch((cause) => {
        setDays((current) => ({
          ...current,
          [date]: {
            date,
            timeline: null,
            status: 'error',
            stored: current[date]?.stored ?? false,
            error: cause instanceof Error ? cause.message : String(cause),
          },
        }));
      })
      .finally(() => {
        inFlight.current.delete(date);
      });
  }, []);

  const ordered: RangeDay[] = dates.map((date) => {
    const known = days[date];
    // The stored flag comes from the day index, which refreshes independently
    // of anything already fetched here.
    if (known) return { ...known, stored: known.status === 'loaded' || storedDates.has(date) };
    return { date, timeline: null, status: 'unfetched', stored: storedDates.has(date) };
  });

  return { days: ordered, load };
}
