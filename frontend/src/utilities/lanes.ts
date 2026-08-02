/** Per-lane visual tokens. Colour is always paired with a text label. */

import type { AccentToken } from '../types/timeline';

export interface AccentTheme {
  /** Line, node stroke, emphasis text. */
  stroke: string;
  /** Filled marks and interval bars. */
  fill: string;
  /** Area under a line, and block fills. */
  soft: string;
  /** Lane row background. */
  band: string;
  /** Label text colour. */
  text: string;
}

export const ACCENTS: Record<AccentToken, AccentTheme> = {
  green: { stroke: '#16a34a', fill: '#22c55e', soft: '#dcfce7', band: '#f6fdf8', text: '#15803d' },
  blue: { stroke: '#2563eb', fill: '#3b82f6', soft: '#dbeafe', band: '#f6f9ff', text: '#1d4ed8' },
  indigo: { stroke: '#4f46e5', fill: '#6366f1', soft: '#e0e7ff', band: '#f8f8ff', text: '#4338ca' },
  purple: { stroke: '#7c3aed', fill: '#8b5cf6', soft: '#ede9fe', band: '#fbf9ff', text: '#6d28d9' },
  orange: { stroke: '#ea580c', fill: '#f97316', soft: '#ffedd5', band: '#fffaf5', text: '#c2410c' },
  teal: { stroke: '#0d9488', fill: '#14b8a6', soft: '#ccfbf1', band: '#f5fdfc', text: '#0f766e' },
  sky: { stroke: '#0284c7', fill: '#0ea5e9', soft: '#e0f2fe', band: '#f6fbff', text: '#0369a1' },
  cyan: { stroke: '#0891b2', fill: '#06b6d4', soft: '#cffafe', band: '#f5fdff', text: '#0e7490' },
  amber: { stroke: '#b45309', fill: '#f59e0b', soft: '#fef3c7', band: '#fffcf4', text: '#92400e' },
  fuchsia: {
    stroke: '#a21caf',
    fill: '#d946ef',
    soft: '#fae8ff',
    band: '#fefaff',
    text: '#86198f',
  },
  rose: { stroke: '#be123c', fill: '#f43f5e', soft: '#ffe4e6', band: '#fff8f9', text: '#9f1239' },
};

export function accentTheme(accent: string): AccentTheme {
  return ACCENTS[accent as AccentToken] ?? ACCENTS.blue;
}

/** Row heights, in px. The label column mirrors these exactly. */
export const LANE_HEIGHTS: Record<string, number> = {
  activity: 118,
  heart_rate: 104,
  hrv: 92,
  readiness: 100,
  sleep: 104,
  temperature: 100,
  environment: 116,
  presence: 106,
  computer_use: 104,
  phone_use: 92,
  tiktok: 84,
  tv: 92,
  location: 96,
};

export const DEFAULT_LANE_HEIGHT = 100;

export function laneHeight(laneId: string): number {
  return LANE_HEIGHTS[laneId] ?? DEFAULT_LANE_HEIGHT;
}

export const LANE_LABEL_WIDTH = 250;
export const AXIS_HEIGHT = 34;

/**
 * Event categories that count as "major" in collapsed mode.
 * Kept explicit so the collapsed view never silently changes meaning.
 */
export const MAJOR_CATEGORIES = new Set([
  // Sleep
  'main_sleep',
  'nap',
  'time_in_bed',
  // Activity sessions
  'strength_training',
  'running',
  'walk',
  'cycling',
  'walking_period',
  // Leaving and coming back
  'left_home',
  'arrived_home',
  'zone_named',
  // One notable physiological stretch — the renderer keeps only the first.
  'elevated',
  // A followed app: a handful of spells a day, and the reason the row exists.
  // Screen-on stretches and ordinary app spells are deliberately *not* here —
  // a phone produces dozens of both, which is a smear rather than a landmark.
  'tiktok',
  // What was on television, by the same test: an evening holds two or three
  // programmes, not forty. The on/off band around them is left out, exactly as
  // the phone's screen-on band is.
  'tv_playing',
]);

export const GRID_LINE = '#e6ebf2';
export const GRID_LINE_MINOR = '#f1f4f9';
export const BASELINE = '#dfe6ef';
export const MISSING_FILL = '#eef1f5';
export const MISSING_STROKE = '#c9d2de';
