/**
 * Right-side details panel: everything known about one selected mark, plus the
 * provenance needed to check it and a button to inspect the raw records.
 */

import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { CloseIcon, LaneIcon } from '../components/Icons';
import type { RawRecordSummary, Selection, TimelineEvent } from '../types/timeline';
import { accentTheme } from '../utilities/lanes';
import { formatDuration, formatIsoDate, formatTime, formatTimeRange } from '../utilities/time';

interface DetailsPanelProps {
  selection: Selection;
  accent: string;
  timeZone: string;
  /** The day the page is showing, so a mark from another one can say so. */
  displayedDate?: string | null;
  onClose: () => void;
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  if (value == null || value === '' || value === '—') return null;
  return (
    <div className="grid grid-cols-[104px_1fr] gap-3 py-[7px]">
      <dt className="text-[11.5px] uppercase tracking-[0.04em] text-slate-400">{label}</dt>
      <dd className="min-w-0 break-words text-[12.5px] leading-relaxed text-slate-700">{value}</dd>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-slate-100 px-5 py-3">
      <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.07em] text-slate-400">
        {title}
      </h3>
      <dl>{children}</dl>
    </section>
  );
}

const METADATA_LABELS: Record<string, string> = {
  activityType: 'Activity type',
  detection: 'Detection',
  steps: 'Steps',
  distanceMeters: 'Distance',
  averageHeartRate: 'Average heart rate',
  maxHeartRate: 'Maximum heart rate',
  activeCalories: 'Active calories',
  efficiency: 'Sleep efficiency',
  sleepScore: 'Sleep score',
  timeInBedMinutes: 'Time in bed',
  awakeMinutes: 'Awake',
  peakBpm: 'Peak',
  meanBpm: 'Mean',
  baselineMeanBpm: 'Baseline mean',
  baselineSdBpm: 'Baseline SD',
  peakZScore: 'Peak z-score',
  concurrentActivity: 'Concurrent activity',
  meanIlluminance: 'Mean illuminance',
  maxIlluminance: 'Maximum illuminance',
  minIlluminance: 'Minimum illuminance',
  classificationRule: 'Classification rule',
  lightCategory: 'Light category',
  sampleCount: 'Samples',
  presenceState: 'Presence state',
  room: 'Room',
  metric: 'Metric',
  personalBaseline: 'Personal baseline',
  deviationFromBaseline: 'Deviation from baseline',
  baselineWindowDays: 'Baseline window',
  zScore: 'z-score',
  extremeValue: 'Extreme value',
  baselineDescription: 'Baseline',
  monitoredEntities: 'Monitored entities',
  durationSeconds: 'Duration',
  reason: 'Reason',
  interpretation: 'Relative to baseline',
};

const UNIT_SUFFIX: Record<string, string> = {
  steps: '',
  distanceMeters: ' m',
  averageHeartRate: ' bpm',
  maxHeartRate: ' bpm',
  activeCalories: ' kcal',
  peakBpm: ' bpm',
  meanBpm: ' bpm',
  baselineMeanBpm: ' bpm',
  baselineSdBpm: ' bpm',
  meanIlluminance: ' lx',
  maxIlluminance: ' lx',
  minIlluminance: ' lx',
  baselineWindowDays: ' days',
  durationSeconds: ' s',
};

const HIDDEN_METADATA = new Set([
  'fullStart',
  'fullEnd',
  'durationMinutes',
  'stages',
  'stageMinutes',
  'note',
  'coversSleepStart',
  'coversSleepEnd',
  'windowStart',
  'windowEnd',
  'newState',
  'previousState',
]);

function formatMetadataValue(key: string, value: unknown): string {
  if (value == null) return '';
  if (Array.isArray(value)) return value.join(' · ');
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') {
    const rounded = Number.isInteger(value) ? value : Number(value.toFixed(2));
    return `${rounded.toLocaleString('en-US')}${UNIT_SUFFIX[key] ?? ''}`;
  }
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function EventBody({
  event,
  timeZone,
  onInspect,
  raw,
  loadingRaw,
}: {
  event: TimelineEvent;
  timeZone: string;
  onInspect: () => void;
  raw: RawRecordSummary[] | null;
  loadingRaw: boolean;
}) {
  const metadata = event.metadata ?? {};
  const fullStart = (metadata.fullStart as string) ?? event.startTime;
  const fullEnd = (metadata.fullEnd as string) ?? event.endTime ?? null;
  const clipped = event.continuesBefore || event.continuesAfter;
  const durationValue =
    typeof metadata.durationMinutes === 'number'
      ? (metadata.durationMinutes as number)
      : fullEnd
        ? (new Date(fullEnd).getTime() - new Date(fullStart).getTime()) / 60000
        : null;

  return (
    <>
      <Section title="When">
        <Row label="Time" value={formatTimeRange(fullStart, fullEnd, timeZone)} />
        <Row label="Duration" value={durationValue != null ? formatDuration(durationValue) : null} />
        {clipped ? (
          <Row
            label="Spans"
            value={
              <span className="text-slate-600">
                {event.continuesBefore ? 'Starts on the previous day. ' : ''}
                {event.continuesAfter ? 'Continues into the next day. ' : ''}
                Drawn clipped to this day; the full timestamps are shown above.
              </span>
            }
          />
        ) : null}
      </Section>

      <Section title="Measurement">
        <Row
          label="Value"
          value={
            event.value != null ? `${event.value}${event.unit ? ` ${event.unit}` : ''}` : null
          }
        />
        <Row label="Event type" value={event.eventType} />
        <Row
          label="Origin"
          value={
            <span
              className={
                event.measuredOrDerived === 'derived'
                  ? 'rounded bg-violet-50 px-1.5 py-0.5 text-violet-700'
                  : 'rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700'
              }
            >
              {event.measuredOrDerived === 'derived' ? 'Derived feature' : 'Measured directly'}
            </span>
          }
        />
        <Row
          label="Confidence"
          value={event.confidence != null ? `${Math.round(event.confidence * 100)}%` : null}
        />
        <Row label="Data quality" value={event.dataQuality} />
      </Section>

      <Section title="Source">
        <Row label="Data source" value={event.source} />
        <Row label="Device" value={event.device} />
        <Row label="Entity ID" value={event.entityId} />
      </Section>

      {Object.keys(metadata).some((key) => !HIDDEN_METADATA.has(key)) ? (
        <Section title="Details">
          {Object.entries(metadata)
            .filter(([key, value]) => !HIDDEN_METADATA.has(key) && value != null && value !== '')
            .map(([key, value]) => (
              <Row
                key={key}
                label={METADATA_LABELS[key] ?? key.replace(/([A-Z])/g, ' $1').toLowerCase()}
                value={formatMetadataValue(key, value)}
              />
            ))}
        </Section>
      ) : null}

      {typeof metadata.note === 'string' ? (
        <div className="border-t border-slate-100 px-5 py-3">
          <p className="rounded-lg bg-slate-50 px-3 py-2 text-[12px] leading-relaxed text-slate-600">
            {metadata.note}
          </p>
        </div>
      ) : null}

      {event.provenance ? (
        <Section title="Provenance">
          <Row label="Rule" value={event.provenance.transformationRule} />
          <Row label="Rule version" value={event.provenance.ruleVersion} />
          <Row
            label="Entities"
            value={
              event.provenance.sourceEntityIds.length ? (
                <ul className="space-y-0.5">
                  {event.provenance.sourceEntityIds.map((entityId) => (
                    <li key={entityId} className="break-all font-mono text-[11px]">
                      {entityId}
                    </li>
                  ))}
                </ul>
              ) : null
            }
          />
          <Row
            label="Thresholds"
            value={
              Object.keys(event.provenance.thresholds).length ? (
                <code className="block whitespace-pre-wrap break-all rounded bg-slate-50 px-2 py-1 font-mono text-[11px] text-slate-600">
                  {JSON.stringify(event.provenance.thresholds, null, 1)}
                </code>
              ) : null
            }
          />
          <Row
            label="Input range"
            value={
              event.provenance.inputTimeRange
                ? formatTimeRange(
                    event.provenance.inputTimeRange[0],
                    event.provenance.inputTimeRange[1],
                    timeZone,
                  )
                : null
            }
          />
          <Row label="Raw records" value={`${event.provenance.rawRecordIds.length}`} />
          {event.provenance.missingDataAssumptions.length ? (
            <Row
              label="Assumptions"
              value={
                <ul className="list-disc space-y-0.5 pl-4">
                  {event.provenance.missingDataAssumptions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              }
            />
          ) : null}
          {event.provenance.notes.length ? (
            <Row
              label="Notes"
              value={
                <ul className="list-disc space-y-0.5 pl-4">
                  {event.provenance.notes.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              }
            />
          ) : null}
        </Section>
      ) : null}

      <div className="border-t border-slate-100 px-5 py-4">
        <button
          type="button"
          onClick={onInspect}
          disabled={loadingRaw}
          className="w-full rounded-lg border border-slate-200 px-3 py-2 text-[12.5px] font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:opacity-60"
        >
          {loadingRaw ? 'Loading raw data…' : 'Inspect raw data'}
        </button>

        {raw ? (
          <div className="mt-3 max-h-64 overflow-y-auto rounded-lg border border-slate-200">
            <table className="w-full border-collapse text-[11.5px]">
              <thead className="sticky top-0 bg-slate-50 text-slate-500">
                <tr>
                  <th className="px-2 py-1.5 text-left font-medium">Time</th>
                  <th className="px-2 py-1.5 text-left font-medium">Stream</th>
                  <th className="px-2 py-1.5 text-right font-medium">Value</th>
                </tr>
              </thead>
              <tbody>
                {raw.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-2 py-3 text-center text-slate-500">
                      This feature has no stored raw records.
                    </td>
                  </tr>
                ) : (
                  raw.map((record) => (
                    <tr key={record.id} className="border-t border-slate-100">
                      <td className="px-2 py-1.5 text-slate-600">
                        {formatTime(record.timestamp, timeZone)}
                      </td>
                      <td className="px-2 py-1.5 text-slate-500">
                        {record.entityId ?? record.stream}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono text-slate-700">
                        {record.value ?? '—'}
                        {record.unit ? ` ${record.unit}` : ''}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </>
  );
}

export function DetailsPanel({
  selection,
  accent,
  timeZone,
  displayedDate,
  onClose,
}: DetailsPanelProps) {
  const [raw, setRaw] = useState<RawRecordSummary[] | null>(null);
  const [loadingRaw, setLoadingRaw] = useState(false);
  const [rawError, setRawError] = useState<string | null>(null);
  const theme = accentTheme(accent);

  useEffect(() => {
    setRaw(null);
    setRawError(null);
  }, [selection]);

  const title = selection.kind === 'event' ? selection.event.label : selection.series.label;
  const subtitle =
    selection.kind === 'event'
      ? formatTimeRange(selection.event.startTime, selection.event.endTime, timeZone)
      : formatTime(selection.point.timestamp, timeZone);

  /**
   * The day this mark came from, named only when it is not the day on screen.
   *
   * A mark picked out of the collapsed strip can belong to any day in the
   * two-month window; showing its times under a page headed "Yesterday"
   * without saying so would attribute one day's events to another.
   */
  const otherDay =
    selection.kind === 'event' && selection.date && selection.date !== displayedDate
      ? selection.date
      : null;

  const loadRaw = async () => {
    if (selection.kind !== 'event') return;
    setLoadingRaw(true);
    setRawError(null);
    try {
      const details = await api.eventDetails(selection.event.id);
      setRaw(details.rawRecords);
    } catch (error) {
      setRawError(
        error instanceof Error
          ? error.message
          : 'Raw records could not be loaded from the local API.',
      );
      setRaw([]);
    } finally {
      setLoadingRaw(false);
    }
  };

  return (
    <aside
      role="complementary"
      aria-label="Event details"
      data-testid="details-panel"
      className="flex w-full flex-col overflow-y-auto rounded-2xl border border-slate-200 bg-white lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:w-[352px] lg:shrink-0"
    >
      <header className="sticky top-0 z-10 flex items-start gap-3 border-b border-slate-100 bg-white px-5 py-4">
        <span
          className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border"
          style={{ borderColor: theme.soft, backgroundColor: theme.band, color: theme.stroke }}
        >
          <LaneIcon laneId={selection.laneId} size={17} />
        </span>
        <span className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold leading-snug text-slate-900">{title}</h2>
          <p className="mt-0.5 text-[12px] text-slate-500">{subtitle}</p>
          {otherDay ? (
            <p
              className="mt-1 text-[11.5px] font-medium text-amber-700"
              data-testid="details-other-day"
            >
              From {formatIsoDate(otherDay)}, not the day on screen
            </p>
          ) : null}
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close details"
          className="rounded-md p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
        >
          <CloseIcon size={16} />
        </button>
      </header>

      {selection.kind === 'event' ? (
        <EventBody
          event={selection.event}
          timeZone={timeZone}
          onInspect={loadRaw}
          raw={raw}
          loadingRaw={loadingRaw}
        />
      ) : (
        <>
          <Section title="Sample">
            <Row label="Time" value={formatTime(selection.point.timestamp, timeZone)} />
            <Row
              label="Value"
              value={`${selection.point.value} ${selection.series.unit}`}
            />
            <Row
              label="Quality"
              value={
                selection.point.quality != null
                  ? `${Math.round(selection.point.quality * 100)}%`
                  : null
              }
            />
          </Section>
          <Section title="Series">
            <Row label="Label" value={selection.series.label} />
            <Row label="Unit" value={selection.series.unit} />
            <Row label="Samples" value={`${selection.series.points.length}`} />
            <Row
              label="Origin"
              value={
                selection.series.measuredOrDerived === 'derived'
                  ? 'Derived feature'
                  : 'Measured directly'
              }
            />
            <Row label="Data source" value={selection.series.source} />
            <Row label="Device" value={selection.series.device} />
            <Row label="Entity ID" value={selection.series.entityId} />
            <Row
              label="Gaps"
              value={
                selection.series.gaps.length
                  ? `${selection.series.gaps.length} missing-data period${
                      selection.series.gaps.length === 1 ? '' : 's'
                    }`
                  : 'None'
              }
            />
          </Section>
          {typeof selection.series.metadata?.note === 'string' ? (
            <div className="border-t border-slate-100 px-5 py-3">
              <p className="rounded-lg bg-slate-50 px-3 py-2 text-[12px] leading-relaxed text-slate-600">
                {selection.series.metadata.note as string}
              </p>
            </div>
          ) : null}
          {selection.series.provenance ? (
            <Section title="Provenance">
              <Row label="Rule" value={selection.series.provenance.transformationRule} />
              <Row label="Rule version" value={selection.series.provenance.ruleVersion} />
              <Row
                label="Raw records"
                value={`${selection.series.provenance.rawRecordIds.length}`}
              />
              {selection.series.provenance.missingDataAssumptions.length ? (
                <Row
                  label="Assumptions"
                  value={
                    <ul className="list-disc space-y-0.5 pl-4">
                      {selection.series.provenance.missingDataAssumptions.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  }
                />
              ) : null}
            </Section>
          ) : null}
        </>
      )}

      {rawError ? (
        <p className="px-5 pb-4 text-[12px] text-rose-600">{rawError}</p>
      ) : null}
    </aside>
  );
}
