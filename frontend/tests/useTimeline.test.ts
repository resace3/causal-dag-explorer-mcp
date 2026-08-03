/**
 * The two timers behind an open page.
 *
 * The poll re-reads what the backend already stored; only the sync goes back to
 * the sources. The distinction matters twice over: a page left open all day
 * would otherwise show hours-old data as current, and a sync pointed at a
 * finished day would overwrite a complete record with the results of a moment.
 */

import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../src/api/client';
import { useTimeline } from '../src/hooks/useTimeline';

const DAY = '2026-08-03';

function fakeTimeline(date = DAY) {
  return { date, generatedAt: new Date().toISOString(), lanes: [] } as never;
}

describe('useTimeline timers', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    // A fresh object per call, deliberately. `mockResolvedValue(fakeTimeline())`
    // evaluates once and hands back the same reference every time, so React
    // bails out of the re-render and `load` never changes identity — which is
    // precisely the condition the reset trap needs, quietly absent.
    vi.spyOn(api, 'day').mockImplementation(async () => fakeTimeline());
    vi.spyOn(api, 'sync').mockImplementation(async () => fakeTimeline());
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('polls the stored day without going back to the sources', async () => {
    renderHook(() => useTimeline(DAY, 1_000, 0));
    await waitFor(() => expect(api.day).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(3_500);

    expect(api.day).toHaveBeenCalledTimes(4);
    expect(api.sync).not.toHaveBeenCalled();
  });

  it('syncs once its deadline has passed, which is what refreshes the data', async () => {
    renderHook(() => useTimeline(DAY, 0, 5_000));
    await waitFor(() => expect(api.day).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(11_000);

    expect(api.sync).toHaveBeenCalledTimes(2);
    expect(api.sync).toHaveBeenCalledWith(DAY);
  });

  it('keeps its deadline across a re-mount rather than starting over', async () => {
    // The bug this replaced: an interval only fires if it survives the whole
    // period. Switching day tears its effect down, so a page touched every few
    // minutes reset a five-minute timer forever and never synced once.
    const { rerender } = renderHook(
      ({ poll }) => useTimeline(DAY, poll, 5_000),
      { initialProps: { poll: 1_000 } },
    );
    await waitFor(() => expect(api.day).toHaveBeenCalledTimes(1));

    // Four seconds of ticking, with the effect rebuilt each second.
    for (let i = 0; i < 4; i += 1) {
      await vi.advanceTimersByTimeAsync(1_000);
      rerender({ poll: 1_000 + i });
    }
    expect(api.sync).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(2_000);
    expect(api.sync).toHaveBeenCalled();
  });

  it('does not sync at all when no interval is asked for', async () => {
    renderHook(() => useTimeline(DAY, 1_000, 0));
    await waitFor(() => expect(api.day).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(60_000);

    expect(api.sync).not.toHaveBeenCalled();
  });

  it('still syncs when a fast poll keeps re-rendering the hook', async () => {
    // `load` is rebuilt whenever the timeline changes, which is every poll; a
    // timer depending on its identity is cleared and restarted before it can
    // come round, so a five-minute sync behind a one-minute poll never fires.
    renderHook(() => useTimeline(DAY, 1_000, 5_000));
    await waitFor(() => expect(api.day).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(11_000);

    expect(vi.mocked(api.day).mock.calls.length).toBeGreaterThan(5);
    expect(api.sync).toHaveBeenCalled();
  });

  it('keeps the timeline on screen when a background sync fails', async () => {
    const { result } = renderHook(() => useTimeline(DAY, 0, 1_000));
    await waitFor(() => expect(result.current.timeline).not.toBeNull());

    vi.mocked(api.sync).mockRejectedValue(new Error('add-on unreachable'));
    await vi.advanceTimersByTimeAsync(1_500);

    // A page left open all day must not be replaced by an error because one
    // source went away for a minute.
    expect(result.current.timeline).not.toBeNull();
    expect(result.current.state).toBe('ready');
  });

  it('does not stack a second sync on one still running', async () => {
    let release: (value: never) => void = () => {};
    vi.mocked(api.sync).mockImplementation(
      () => new Promise((resolve) => {
        release = resolve as (value: never) => void;
      }),
    );
    renderHook(() => useTimeline(DAY, 0, 1_000));
    await waitFor(() => expect(api.day).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(3_500);

    expect(api.sync).toHaveBeenCalledTimes(1);
    release(fakeTimeline());
  });
});
