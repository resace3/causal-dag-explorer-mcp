import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, api } from '../api/client';
import type { DayTimeline } from '../types/timeline';

export type LoadState = 'loading' | 'ready' | 'error';

interface TimelineState {
  timeline: DayTimeline | null;
  state: LoadState;
  error: ApiError | null;
  refreshing: boolean;
  refresh: () => Promise<void>;
  reload: () => Promise<void>;
}

/**
 * Loads one local calendar day, then re-checks periodically so an MCP
 * `refresh_timeline` call reaches an already-open page.
 *
 * `date` stays null until the backend has said which day "yesterday" is, so the
 * browser's timezone can never disagree with the server's about which day to
 * show. The previous timeline stays on screen while a refresh is in flight,
 * which keeps the selected event mounted rather than unmounting the whole view.
 */
export function useTimeline(date: string | null, pollIntervalMs = 60_000): TimelineState {
  const [timeline, setTimeline] = useState<DayTimeline | null>(null);
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState<ApiError | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const mounted = useRef(true);
  const current = useRef<string | null>(date);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(
    async (mode: 'initial' | 'poll' | 'force', target: string | null) => {
      if (target === null) return;
      current.current = target;
      if (mode === 'force') setRefreshing(true);
      if (mode === 'initial') setState('loading');

      try {
        const next = mode === 'force' ? await api.sync(target) : await api.day(target);
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
        // A failed poll must not blank a timeline that is already on screen.
        if (mode === 'poll' && timeline) return;
        setError(apiError);
        setState('error');
      } finally {
        if (mounted.current) setRefreshing(false);
      }
    },
    [timeline],
  );

  useEffect(() => {
    if (date === null) return;
    void load('initial', date);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date]);

  useEffect(() => {
    if (pollIntervalMs <= 0 || date === null) return undefined;
    const handle = window.setInterval(() => void load('poll', date), pollIntervalMs);
    return () => window.clearInterval(handle);
  }, [load, pollIntervalMs, date]);

  return {
    timeline,
    state,
    error,
    refreshing,
    refresh: () => load('force', date),
    reload: () => load('initial', date),
  };
}
