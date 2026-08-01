/**
 * View preferences are choices about your own view, not data. Losing one on a
 * reload, or in the next tab, makes the control that set it not worth using.
 */

import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { isStringArray, usePersistentState } from '../src/hooks/usePersistentState';

const PREFIX = 'yesterday-timeline:';

/** What the browser fires in *other* tabs when one of them writes. */
function storageEvent(key: string, newValue: string | null) {
  window.dispatchEvent(
    new StorageEvent('storage', { key: PREFIX + key, newValue, storageArea: localStorage }),
  );
}

describe('usePersistentState', () => {
  beforeEach(() => localStorage.clear());

  it('survives a reload', () => {
    const first = renderHook(() => usePersistentState<string[]>('hidden-lanes', [], isStringArray));
    act(() => first.result.current[1](['environment', 'hrv']));
    first.unmount();

    // A fresh mount is what a reload, or a second tab opening, actually is.
    const second = renderHook(() => usePersistentState<string[]>('hidden-lanes', [], isStringArray));
    expect(second.result.current[0]).toEqual(['environment', 'hrv']);
  });

  it('follows the same preference changing in another tab', () => {
    const { result } = renderHook(() =>
      usePersistentState<string[]>('hidden-lanes', [], isStringArray),
    );
    act(() => storageEvent('hidden-lanes', JSON.stringify(['sleep'])));
    expect(result.current[0]).toEqual(['sleep']);
  });

  it('ignores an echo of its own write, so two tabs cannot ping-pong', () => {
    const { result } = renderHook(() =>
      usePersistentState<string[]>('hidden-lanes', [], isStringArray),
    );
    act(() => result.current[1](['sleep']));

    const before = result.current[0];
    act(() => storageEvent('hidden-lanes', JSON.stringify(['sleep'])));
    // Identical text: the value must not even be replaced with an equal copy,
    // or the write effect fires again and the exchange never settles.
    expect(result.current[0]).toBe(before);
  });

  it('ignores another key entirely', () => {
    const { result } = renderHook(() =>
      usePersistentState<string[]>('hidden-lanes', [], isStringArray),
    );
    act(() => storageEvent('lane-order', JSON.stringify(['activity'])));
    expect(result.current[0]).toEqual([]);
  });

  it('keeps what it has when another tab writes something unreadable', () => {
    const { result } = renderHook(() =>
      usePersistentState<string[]>('hidden-lanes', [], isStringArray),
    );
    act(() => result.current[1](['sleep']));
    act(() => storageEvent('hidden-lanes', '{not json'));
    expect(result.current[0]).toEqual(['sleep']);

    // Wrong shape is refused by the validator for the same reason.
    act(() => storageEvent('hidden-lanes', JSON.stringify({ sleep: true })));
    expect(result.current[0]).toEqual(['sleep']);
  });

  it('returns to the default when the key is cleared elsewhere', () => {
    const { result } = renderHook(() =>
      usePersistentState<string[]>('hidden-lanes', [], isStringArray),
    );
    act(() => result.current[1](['sleep']));
    act(() => storageEvent('hidden-lanes', null));
    expect(result.current[0]).toEqual([]);
  });

  it('refuses a stored value of the wrong shape rather than rendering it', () => {
    localStorage.setItem(`${PREFIX}hidden-lanes`, JSON.stringify({ nope: 1 }));
    const { result } = renderHook(() =>
      usePersistentState<string[]>('hidden-lanes', [], isStringArray),
    );
    expect(result.current[0]).toEqual([]);
  });
});
