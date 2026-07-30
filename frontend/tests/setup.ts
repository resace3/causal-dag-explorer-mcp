import '@testing-library/jest-dom/vitest';

// jsdom has no ResizeObserver; the timeline uses it to track its own width.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;

if (!Element.prototype.getBoundingClientRect.call) {
  /* noop */
}

// jsdom reports zero-size elements; give the plot a believable width.
Element.prototype.getBoundingClientRect = function getBoundingClientRect() {
  return {
    width: 1000,
    height: 100,
    top: 0,
    left: 0,
    right: 1000,
    bottom: 100,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect;
};
