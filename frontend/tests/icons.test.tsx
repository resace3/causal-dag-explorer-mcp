/**
 * A DAG node shows a glyph and a time; the row label is off to the left. So the
 * glyph has to be the thing that says which variable a node is, and two
 * variables sharing a lane must not share a glyph.
 */

import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { VariableIcon } from '../src/components/Icons';

/** Mirrors `server/app/causal/knowledge.py`. */
const VARIABLES = [
  'exercise',
  'step_count',
  'sleep_duration',
  'sleep_onset',
  'sleep_efficiency',
  'resting_heart_rate',
  'hrv',
  'readiness',
  'light_evening',
  'light_morning',
  'room_temperature',
  'skin_temperature',
  'device_use',
  'time_away',
  'location',
  'day_of_week',
  'circadian_phase',
  'stress',
  'alcohol',
  'caffeine',
  'illness',
  'work_schedule',
];

function markup(variable: string): string {
  const { container } = render(<VariableIcon variable={variable} />);
  return container.innerHTML;
}

describe('variable icons', () => {
  it('gives every causal variable its own glyph rather than a fallback', () => {
    const fallback = markup('a-variable-that-does-not-exist');
    const missing = VARIABLES.filter((variable) => markup(variable) === fallback);
    expect(missing).toEqual([]);
  });

  it('never reuses one glyph for two variables', () => {
    const seen = new Map<string, string>();
    for (const variable of VARIABLES) {
      const glyph = markup(variable);
      const clash = seen.get(glyph);
      expect(clash, `${variable} and ${clash} draw the same icon`).toBeUndefined();
      seen.set(glyph, variable);
    }
  });

  it('distinguishes the three sleep variables, which share one lane', () => {
    const glyphs = new Set(
      ['sleep_duration', 'sleep_onset', 'sleep_efficiency'].map((item) => markup(item)),
    );
    expect(glyphs.size).toBe(3);
  });

  it('renders an svg that inherits colour from its container', () => {
    const { container } = render(<VariableIcon variable="exercise" size={20} />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('width')).toBe('20');
    // `currentColor` is what lets one glyph be white on a node and slate in the
    // row label without a second copy of the icon.
    expect(svg?.getAttribute('stroke')).toBe('currentColor');
  });

  it('hides icons from assistive technology, since each is labelled in text', () => {
    const { container } = render(<VariableIcon variable="sleep_duration" />);
    expect(container.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
  });
});
