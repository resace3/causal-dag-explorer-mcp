import type { DayTimeline, Lane, TimelineEvent, TimelineSeries } from '../src/types/timeline';

const DAY_START = '2025-06-10T00:00:00-04:00';
const DAY_END = '2025-06-11T00:00:00-04:00';

export function makeEvent(overrides: Partial<TimelineEvent> = {}): TimelineEvent {
  return {
    id: 'activity_morning',
    phenotype: 'activity',
    label: 'Morning workout',
    eventType: 'interval',
    startTime: '2025-06-10T07:15:00-04:00',
    endTime: '2025-06-10T08:00:00-04:00',
    value: 45,
    unit: 'min',
    source: 'wearable:mock',
    device: 'Mock Band 3',
    entityId: null,
    measuredOrDerived: 'measured',
    confidence: 0.98,
    dataQuality: 'high',
    category: 'strength_training',
    continuesBefore: false,
    continuesAfter: false,
    metadata: { durationMinutes: 45, averageHeartRate: 132 },
    provenance: {
      rawRecordIds: ['raw_activity_1'],
      sourceEntityIds: [],
      transformationRule: 'activity.workout_session',
      ruleVersion: '1.1.0',
      thresholds: { min_duration_minutes: 5 },
      inputTimeRange: null,
      outputTimestamp: null,
      missingDataAssumptions: [],
      notes: [],
    },
    ...overrides,
  };
}

export function makeSeries(overrides: Partial<TimelineSeries> = {}): TimelineSeries {
  return {
    id: 'series_heart_rate',
    phenotype: 'heart_rate',
    label: 'Heart rate',
    unit: 'bpm',
    source: 'wearable:mock',
    device: 'Mock Band 3',
    entityId: null,
    measuredOrDerived: 'measured',
    points: [
      { timestamp: '2025-06-10T00:00:00-04:00', value: 58 },
      { timestamp: '2025-06-10T06:00:00-04:00', value: 62 },
      { timestamp: '2025-06-10T12:00:00-04:00', value: 88 },
      { timestamp: '2025-06-10T18:00:00-04:00', value: 74 },
      { timestamp: '2025-06-10T23:00:00-04:00', value: 61 },
    ],
    gaps: [],
    minValue: 58,
    maxValue: 88,
    style: 'primary',
    metadata: {},
    provenance: null,
    ...overrides,
  };
}

export function makeLane(overrides: Partial<Lane> = {}): Lane {
  return {
    id: 'activity',
    phenotype: 'activity',
    label: 'Activity',
    description: 'Exercise and movement',
    accent: 'green',
    available: true,
    unavailableReason: null,
    units: ['min'],
    events: [makeEvent()],
    series: [],
    sources: ['wearable:mock'],
    ...overrides,
  };
}

export function makeTimeline(overrides: Partial<DayTimeline> = {}): DayTimeline {
  const lanes: Lane[] = overrides.lanes ?? [
    makeLane(),
    makeLane({
      id: 'heart_rate',
      phenotype: 'heart_rate',
      label: 'Heart Rate',
      description: 'Wearable cardiovascular signal',
      accent: 'blue',
      units: ['bpm'],
      events: [],
      series: [makeSeries()],
    }),
    makeLane({
      id: 'sleep',
      phenotype: 'sleep',
      label: 'Sleep',
      description: 'Sleep periods and stages',
      accent: 'orange',
      events: [
        makeEvent({
          id: 'sleep_main',
          phenotype: 'sleep',
          label: 'Main sleep',
          category: 'main_sleep',
          startTime: DAY_START,
          endTime: '2025-06-10T07:00:00-04:00',
          continuesBefore: true,
          metadata: {
            durationMinutes: 470,
            fullStart: '2025-06-09T23:10:00-04:00',
            fullEnd: '2025-06-10T07:00:00-04:00',
          },
        }),
      ],
      series: [],
    }),
    makeLane({
      id: 'hrv',
      phenotype: 'hrv',
      label: 'Heart Rate Variability',
      description: 'Nightly beat-to-beat variation',
      accent: 'indigo',
      available: false,
      unavailableReason: 'No HRV data was available yesterday.',
      events: [],
      series: [],
    }),
  ];

  return {
    date: '2025-06-10',
    localTimezone: 'America/New_York',
    dayStart: DAY_START,
    dayEnd: DAY_END,
    dayLengthHours: 24,
    generatedAt: '2025-06-11T09:00:00-04:00',
    lanes,
    summary: {
      dateProcessed: '2025-06-10',
      localTimezone: 'America/New_York',
      dayStart: DAY_START,
      dayEnd: DAY_END,
      dayLengthHours: 24,
      sourcesChecked: ['Home Assistant', 'Wearables'],
      rawRecordCount: 1830,
      normalizedEventCount: 12,
      derivedFeatureCount: 5,
      seriesPointCount: 5,
      coverage: { overallFraction: 0.93, perLane: {}, missingPeriods: [] },
      warnings: [],
      errors: [],
      startedAt: '2025-06-11T09:00:00-04:00',
      completedAt: '2025-06-11T09:00:02-04:00',
    },
    highlights: ['Morning workout ended 15.2 hours before the recorded sleep onset.'],
    mockData: true,
    ...overrides,
  };
}
