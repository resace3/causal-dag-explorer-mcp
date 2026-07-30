import { useEffect, useRef, useState } from 'react';

/** Tracks an element's width so the SVG can be re-laid out on resize. */
export function useElementWidth<T extends HTMLElement>(fallback = 900) {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);

  useEffect(() => {
    const element = ref.current;
    if (!element) return undefined;

    const measure = () => setWidth(Math.round(element.getBoundingClientRect().width) || fallback);
    measure();

    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure);
      return () => window.removeEventListener('resize', measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [fallback]);

  return { ref, width };
}
