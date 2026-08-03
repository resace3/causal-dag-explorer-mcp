import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, api } from '../api/client';
import type { DayTimeline } from '../types/timeline';

export type LoadState = 'loading' | 'ready' | 'error';

/**
 * `poll` re-reads the stored day; `auto` and `force` go back to the sources.
 *
 * The difference that matters is what a failure does. A user who pressed
 * Refresh is waiting for an answer and gets the error. A timer firing in the
 * background must never replace a timeline already on screen with an error
 * message — the page is left open all day, and a single unreachable source
 * would otherwise wipe it while nobody was looking.
 */
type LoadMode = 'initial' | 'poll' | 'auto' | 'force';

interface TimelineState {
  timeline: DayTimeline | null;
  state: LoadState;
  error: ApiError | null;
  refreshing: boolean;
  refresh: () => Promise<void>;
  reload: () => Promise<void>;
}

/**
 * Loads one local calendar day, then keeps it current on two timers.
 *
 * `pollIntervalMs` re-reads what the backend already has, so an MCP
 * `refresh_timeline` call or another tab reaches an open page. It is cheap and
 * reads the cache; on its own it will happily show hours-old data as though it
 * were current, because nothing it does asks the sources anything.
 *
 * `syncIntervalMs` is the one that actually refreshes the data, and it is off
 * unless a caller asks for it. **Pass it only for a day still in progress.** A
 * sync overwrites the stored day with whatever the sources answer at that
 * moment, so putting a finished day on a repeating sync would keep replacing a
 * complete record with the results of a moment — and one unreachable source
 * would degrade it permanently.
 *
 * `date` stays null until the backend has said which day "yesterday" is, so the
 * browser's timezone can never disagree with the server's about which day to
 * show. The previous timeline stays on screen while a refresh is in flight,
 * which keeps the selected event mounted rather than unmounting the whole view.
 */
export function useTimeline(
  date: string | null,
  pollIntervalMs = 60_000,
  syncIntervalMs = 0,
): TimelineState {
  const [timeline, setTimeline] = useState<DayTimeline | null>(null);
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState<ApiError | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const mounted = useRef(true);
  const current = useRef<string | null>(date);
  const inFlight = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(
    async (mode: LoadMode, target: string | null) => {
      if (target === null) return;
      // A sync takes tens of seconds against live sources. Without this, a
      // timer firing mid-sync stacks a second one on it, and the two race to
      // write the same day.
      if (inFlight.current && mode !== 'initial') return;
      inFlight.current = true;

      current.current = target;
      const fromSource = mode === 'force' || mode === 'auto';
      if (fromSource) setRefreshing(true);
      if (mode === 'initial') setState('loading');

      try {
        const next = fromSource ? await api.sync(target) : await api.day(target);
        // A slow request for a day the user has already navigated away from
        // must not overwrite what is on screen.
        if (!mounted.current || current.current !== target) return;
        setTimeline(next);
        setState('ready');
        setError(null);
      } catch (cause) {
        if (!mounted.current || current.current !== target) return;
        const apiError =
          cause instanceof ApiError ? cause : new ApiError(String(cause), 'unexpected_error', 0);
        // Neither timer may blank a timeline that is already on screen.
        if ((mode === 'poll' || mode === 'auto') && timeline) return;
        setError(apiError);
        setState('error');
      } finally {
        inFlight.current = false;
        if (mounted.current) setRefreshing(false);
      }
    },
    [timeline],
  );

  // `load` is rebuilt whenever the timeline changes, which is every poll. The
  // timer below must not depend on its identity: an interval rebuilt on every
  // poll is an interval that restarts before it can fire.
  const latest = useRef(load);
  useEffect(() => {
    latest.current = load;
  }, [load]);

  useEffect(() => {
    if (date === null) return;
    void load('initial', date);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date]);

  /**
   * When the day was last read from its sources, rather than from the cache.
   *
   * The sync cadence is a deadline held here, not a second interval. An
   * interval only fires if it survives `syncIntervalMs` uninterrupted, and this
   * one would not: changing day tears its effect down and starts the countdown
   * again, so a page touched every few minutes would keep resetting a
   * five-minute timer and never sync at all. A deadline survives every
   * teardown, because the clock does not care how many times the effect ran.
   */
  const lastSync = useRef(Date.now());

  useEffect(() => {
    const tickMs = pollIntervalMs > 0 ? pollIntervalMs : syncIntervalMs;
    if (tickMs <= 0 || date === null) return undefined;

    const handle = window.setInterval(() => {
      const due = syncIntervalMs > 0 && Date.now() - lastSync.current >= syncIntervalMs;
      if (due) lastSync.current = Date.now();
      void latest.current(due ? 'auto' : 'poll', date);
    }, tickMs);
    return () => window.clearInterval(handle);
  }, [pollIntervalMs, syncIntervalMs, date]);

  return {
    timeline,
    state,
    error,
    refreshing,
    refresh: () => load('force', date),
    reload: () => load('initial', date),
  };
}
