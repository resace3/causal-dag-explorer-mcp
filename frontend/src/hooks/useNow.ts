import { useEffect, useState } from 'react';

/**
 * The current instant, re-read on a slow tick.
 *
 * Thirty seconds rather than a second: the only consumer is the "now" line, a
 * day is around a thousand pixels wide, and one pixel is therefore about a
 * minute and a half. A per-second timer would re-render the whole timeline
 * ninety times to move the line once.
 *
 * `active` is false for a day that has already ended, where there is no present
 * moment to draw and no reason to hold a timer open.
 */
const TICK_MS = 30_000;

export function useNow(active: boolean): Date | null {
  const [now, setNow] = useState<Date | null>(() => (active ? new Date() : null));

  useEffect(() => {
    if (!active) {
      setNow(null);
      return;
    }
    setNow(new Date());
    const id = window.setInterval(() => setNow(new Date()), TICK_MS);
    return () => window.clearInterval(id);
  }, [active]);

  return now;
}
