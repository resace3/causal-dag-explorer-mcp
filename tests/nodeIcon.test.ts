import { describe, expect, it } from 'vitest';
import { resolveNodeIcon } from '../src/shared/nodeIcon';

describe('semantic node logos', () => {
  it('maps the five-node example to meaningful logos', () => {
    expect(resolveNodeIcon('Exercise')).toBe('activity');
    expect(resolveNodeIcon('Sleep')).toBe('sleep');
    expect(resolveNodeIcon('Stress')).toBe('stress');
    expect(resolveNodeIcon('Mood')).toBe('mood');
    expect(resolveNodeIcon('Productivity')).toBe('productivity');
  });

  it('supports Home Assistant-style environmental labels', () => {
    expect(resolveNodeIcon('Bedroom temperature')).toBe('temperature');
    expect(resolveNodeIcon('Night humidity')).toBe('humidity');
    expect(resolveNodeIcon('Late evening light')).toBe('light');
  });

  it('uses a neutral diagram logo for custom labels', () => {
    expect(resolveNodeIcon('My custom box')).toBe('generic');
  });

  it('honors known explicit icons but upgrades legacy letters from the label', () => {
    expect(resolveNodeIcon('Morning routine', 'coffee')).toBe('caffeine');
    expect(resolveNodeIcon('Sleep', 'S')).toBe('sleep');
  });
});
