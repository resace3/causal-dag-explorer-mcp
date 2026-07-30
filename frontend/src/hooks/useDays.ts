import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, type DayIndex, type DaysResponse } from '../api/client';

/**
 * The calendar's index of which days already hold a processed timeline.
 *
 * Reloaded whenever a day finishes syncing, so a freshly fetched day gets its
 * marker without a page refresh.
 */
export function useDays(refreshToken: unknown) {
  const [response, setResponse] = useState<DaysResponse | null>(null);

  const load = useCallback(async () => {
    try {
      setResponse(await api.days());
    } catch {
      // The calendar still works without the index; days are simply unmarked.
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, refreshToken]);

  const index = useMemo(() => {
    const map = new Map<string, DayIndex>();
    for (const day of response?.days ?? []) map.set(day.date, day);
    return map;
  }, [response]);

  return { index, today: response?.today ?? null, yesterday: response?.yesterday ?? null };
}
