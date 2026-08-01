/** Loading, error and empty states. Every message names the actual problem. */

import type { ApiError } from '../api/client';
import { InfoIcon } from './Icons';

export function TimelineSkeleton() {
  return (
    <div className="animate-pulse px-5 py-6" data-testid="timeline-skeleton" aria-busy="true">
      <div className="mb-5 h-3 w-40 rounded bg-slate-100" />
      {[0, 1, 2, 3, 4, 5].map((row) => (
        <div key={row} className="mb-3 flex items-center gap-4">
          <div className="flex w-[200px] shrink-0 items-center gap-3">
            <div className="h-9 w-9 rounded-full bg-slate-100" />
            <div className="flex-1 space-y-1.5">
              <div className="h-2.5 w-24 rounded bg-slate-100" />
              <div className="h-2 w-16 rounded bg-slate-50" />
            </div>
          </div>
          <div className="h-12 flex-1 rounded-lg bg-slate-50" />
        </div>
      ))}
      <p className="sr-only">Loading the day&rsquo;s timeline…</p>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  return (
    <div
      role="alert"
      data-testid="error-state"
      className="m-5 rounded-xl border border-rose-200 bg-rose-50/50 px-5 py-4"
    >
      <h2 className="text-[14px] font-semibold text-rose-900">
        {error.code === 'backend_unreachable'
          ? 'The local backend is not running'
          : 'This day could not be loaded'}
      </h2>
      <p className="mt-1.5 text-[12.5px] leading-relaxed text-rose-800">{error.message}</p>
      {error.hint ? <p className="mt-1 text-[12px] text-rose-700/80">{error.hint}</p> : null}
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 rounded-lg border border-rose-300 bg-white px-3 py-1.5 text-[12.5px] font-medium text-rose-800 transition hover:bg-rose-50"
      >
        Try again
      </button>
    </div>
  );
}

export function SourceNotices({
  warnings,
  errors,
}: {
  warnings: string[];
  errors: string[];
}) {
  if (!warnings.length && !errors.length) return null;

  return (
    <div className="space-y-2 px-8 pb-4" data-testid="source-notices">
      {errors.map((message) => (
        <p
          key={message}
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50/60 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-rose-800"
        >
          <InfoIcon size={15} className="mt-0.5 shrink-0" />
          {message}
        </p>
      ))}
      {warnings.map((message) => (
        <p
          key={message}
          className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50/60 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-amber-900"
        >
          <InfoIcon size={15} className="mt-0.5 shrink-0" />
          {message}
        </p>
      ))}
    </div>
  );
}

export function EmptyLaneNotice({ label, reason }: { label: string; reason: string }) {
  return (
    <p className="px-5 py-2 text-[12px] text-slate-400">
      <span className="font-medium text-slate-500">{label}</span> — {reason}
    </p>
  );
}
