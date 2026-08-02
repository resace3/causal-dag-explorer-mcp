"""Runs of a categorical sensor, cut against the periods a device was on.

Three rows need this and they all need it for the same reason. Android's "last
used app" sensor, and a television's media-title sensor, both report a change
and then hold that value indefinitely — screen on, screen off, device unplugged.
The run that follows the last app of the evening therefore covers the whole
night, and the run following the last episode covers every hour until the set
is next switched on.

Neither run is evidence of anything. What is evidence is the intersection of
that run with the periods the device was demonstrably on, so that intersection
is computed in one place rather than reimplemented per row, where the two copies
would drift and only one of them would be wrong.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ...models.raw import NormalizedState


def on_windows(states: list[NormalizedState]) -> list[tuple[datetime, datetime]]:
    """The raw on-spans, unmerged.

    Session tiers bridge short gaps so the drawn bars read as sessions; clipping
    a spell has to use the unbridged windows instead, or a five-minute pocket
    gap would silently become five minutes in an app.
    """
    return sorted(
        (state.start_time, state.end_time)
        for state in states
        if state.end_time > state.start_time
    )


def clipped_spells(
    states: list[NormalizedState],
    windows: list[tuple[datetime, datetime]],
    merge_within: timedelta,
    *,
    values: set[str] | None = None,
) -> list[tuple[str, datetime, datetime, list[str], NormalizedState]]:
    """Runs of one sensor value, clipped to the windows the device was on.

    Returns `(value, start, end, raw_record_ids, sample)` per spell. `values`
    keeps only the named ones, which is how the TikTok row follows two packages.

    Runs are built from every value first and filtered afterwards, never the
    other way round. Filtering first would let two spells either side of a
    glance at the home screen merge across it, quietly relabelling that glance —
    a row that exists to say how long was spent on one thing must not round up.
    """
    if not states or not windows:
        return []

    ordered = sorted(states, key=lambda item: item.start_time)
    runs: list[tuple[str, datetime, datetime, list[str]]] = []
    for state in ordered:
        value = state.state
        if not value or value.startswith("__"):
            continue  # unavailable, or a hole the normalizer marked
        if runs and runs[-1][0] == value and state.start_time - runs[-1][2] <= merge_within:
            current, start, previous_end, ids = runs[-1]
            runs[-1] = (
                current,
                start,
                max(previous_end, state.end_time),
                [*ids, *state.raw_record_ids],
            )
            continue
        runs.append((value, state.start_time, state.end_time, list(state.raw_record_ids)))

    by_start = {state.start_time: state for state in ordered}

    spells: list[tuple[str, datetime, datetime, list[str], NormalizedState]] = []
    for value, run_start, run_end, ids in runs:
        if values is not None and value not in values:
            continue
        sample = by_start.get(run_start, ordered[0])
        for window_start, window_end in windows:
            start = max(run_start, window_start)
            end = min(run_end, window_end)
            if end > start:
                spells.append((value, start, end, ids, sample))
    spells.sort(key=lambda spell: spell[1])
    return spells


def value_at(states: list[NormalizedState], moment: datetime) -> NormalizedState | None:
    """The state a categorical sensor was holding at `moment`, if any.

    Used to annotate a spell from one stream with a second stream's value —
    which app a television title was playing under. Deliberately not merged into
    the spell itself: the annotation is read at a single instant, and treating
    it as though it spanned the whole spell would claim more than was sampled.
    """
    for state in states:
        if state.start_time <= moment < state.end_time:
            if state.state and not state.state.startswith("__"):
                return state
            return None
    return None
