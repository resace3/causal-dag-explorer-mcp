/**
 * Page header. The status card reports facts about the reconstruction —
 * coverage, sources, event counts — and never evaluates the user's day.
 */

import { CheckIcon, InfoIcon } from './Icons';
import type { DayTimeline } from '../types/timeline';
import { formatIsoDate, formatRelativeToNow } from '../utilities/time';

function StatusCard({ timeline }: { timeline: DayTimeline }) {
  const summary = timeline.summary;
  const coverage = Math.round((summary.coverage?.overallFraction ?? 0) * 100);
  const sourceCount = summary.sourcesChecked.length;
  const missingCount = summary.coverage?.missingPeriods?.length ?? 0;
  const failed = summary.errors.length > 0;

  const headline = failed
    ? 'Day partially reconstructed'
    : 'Day successfully reconstructed';

  const facts = [
    `Data available from ${sourceCount} source${sourceCount === 1 ? '' : 's'}`,
    `${summary.normalizedEventCount} events · ${summary.seriesPointCount} samples · ${coverage}% coverage`,
    missingCount
      ? `${missingCount} missing period${missingCount === 1 ? '' : 's'}`
      : 'No missing periods detected',
    `Last synchronized ${formatRelativeToNow(summary.completedAt ?? timeline.generatedAt)}`,
  ];

  return (
    <div
      className="flex w-full max-w-[380px] items-start gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3"
      data-testid="status-card"
    >
      <span
        className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
          failed ? 'bg-amber-50 text-amber-600' : 'bg-emerald-50 text-emerald-600'
        }`}
      >
        {failed ? <InfoIcon size={17} /> : <CheckIcon size={17} />}
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] font-semibold text-slate-800">{headline}</span>
        <span className="mt-0.5 block space-y-0.5 text-[11.5px] leading-snug text-slate-500">
          {facts.map((fact) => (
            <span key={fact} className="block">
              {fact}
            </span>
          ))}
        </span>
      </span>
    </div>
  );
}

interface PageHeaderProps {
  timeline: DayTimeline | null;
  /** The day being shown, so the title is right before the payload arrives. */
  selectedDate: string | null;
  yesterday: string | null;
  today: string | null;
}

export function PageHeader({ timeline, selectedDate, yesterday, today }: PageHeaderProps) {
  // The requested day wins: while a new day loads, the title must name what
  // was asked for rather than the timeline still being displaced.
  const date = selectedDate ?? timeline?.date ?? null;
  const isYesterday = date !== null && date === yesterday;
  const isToday = date !== null && date === today;
  const title = isYesterday ? 'Yesterday' : isToday ? 'Today' : date ? formatIsoDate(date) : 'Day';
  return (
    <header className="flex flex-wrap items-start justify-between gap-4 px-8 pb-5 pt-7">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[34px] font-semibold leading-none tracking-[-0.02em] text-slate-900">
            {title}
          </h1>
          <span className="rounded-md bg-blue-50 px-2.5 py-1 text-[12px] font-medium text-blue-700">
            Auto-updated
          </span>
          {isToday ? (
            <span
              className="rounded-md bg-slate-100 px-2.5 py-1 text-[12px] font-medium text-slate-600"
              title="Today is still in progress, so this day is incomplete by definition."
            >
              In progress
            </span>
          ) : null}
          {timeline?.mockData ? (
            <span
              className="rounded-md bg-amber-50 px-2.5 py-1 text-[12px] font-medium text-amber-700"
              title="All values on this page are generated locally; no real sensor data is shown."
            >
              Mock data
            </span>
          ) : null}
        </div>
        <p className="mt-2 text-[14px] text-slate-500">
          {isToday
            ? 'Your data from today so far, from 12:00 AM'
            : `Your data from ${isYesterday ? 'yesterday' : 'this day'}, 12:00 AM to 11:59 PM`}
          {date ? (
            <span className="text-slate-400">
              {' · '}
              {formatIsoDate(date)}
              {timeline ? ` · ${timeline.localTimezone}` : ''}
            </span>
          ) : null}
        </p>
      </div>
      {timeline && timeline.date === date ? <StatusCard timeline={timeline} /> : null}
    </header>
  );
}
