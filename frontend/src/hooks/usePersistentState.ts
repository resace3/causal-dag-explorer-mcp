/**
 * State that survives a reload, kept in localStorage.
 *
 * Used for view preferences — lane order, which phenotypes are shown — rather
 * than for anything derived from the data. The distinction matters: sensor data
 * lives in SQLite on the server and is re-derivable, whereas these are choices
 * the user made about their own view, and losing them on every refresh would
 * make the controls not worth using.
 *
 * Reads are defensive. A stored value written by an older version of the app,
 * or edited by hand, must not be able to stop the page rendering.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

const PREFIX = 'yesterday-timeline:';

function read<T>(key: string, fallback: T, validate?: (value: unknown) => value is T): T {
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    if (raw === null) return fallback;
    const parsed: unknown = JSON.parse(raw);
    if (validate && !validate(parsed)) return fallback;
    return parsed as T;
  } catch {
    return fallback;
  }
}

export function usePersistentState<T>(
  key: string,
  fallback: T,
  validate?: (value: unknown) => value is T,
): [T, (value: T | ((current: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => read(key, fallback, validate));
  // Keeping the validator in a ref stops an inline predicate — which is a new
  // function identity every render — from re-running the effect forever.
  const validateRef = useRef(validate);
  validateRef.current = validate;
  const fallbackRef = useRef(fallback);
  fallbackRef.current = fallback;

  /**
   * The last text this tab wrote or accepted, so a change can be told apart
   * from an echo of itself. Without it the two tabs below hand the same value
   * back and forth forever: each write fires the other's listener, whose
   * `setValue` triggers a write, which fires the first tab's listener again.
   */
  const lastSeen = useRef<string | null>(null);

  useEffect(() => {
    try {
      const raw = JSON.stringify(value);
      if (raw === lastSeen.current) return;
      lastSeen.current = raw;
      window.localStorage.setItem(PREFIX + key, raw);
    } catch {
      // A full or unavailable store is not worth breaking the page over.
    }
  }, [key, value]);

  /**
   * Follow the same preference changing in another tab.
   *
   * This page is opened automatically at login and left open, so two tabs at
   * once is the normal case rather than the exotic one. Without this, the older
   * tab keeps its stale arrangement and the next thing it writes silently
   * discards what you did in the newer one.
   */
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== PREFIX + key) return;
      if (event.newValue === lastSeen.current) return;
      lastSeen.current = event.newValue;

      if (event.newValue === null) {
        setValue(fallbackRef.current);
        return;
      }
      try {
        const parsed: unknown = JSON.parse(event.newValue);
        if (validateRef.current && !validateRef.current(parsed)) return;
        setValue(parsed as T);
      } catch {
        // Another tab wrote something unreadable; keep what this one has.
      }
    };

    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [key]);

  const update = useCallback((next: T | ((current: T) => T)) => {
    setValue((current) =>
      typeof next === 'function' ? (next as (current: T) => T)(current) : next,
    );
  }, []);

  return [value, update];
}

export function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}
