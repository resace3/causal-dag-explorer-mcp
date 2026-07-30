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

  useEffect(() => {
    try {
      window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
    } catch {
      // A full or unavailable store is not worth breaking the page over.
    }
  }, [key, value]);

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
