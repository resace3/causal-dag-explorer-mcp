/**
 * Month calendar for picking which day to reconstruct.
 *
 * A filled dot marks a day already processed and holding events; a hollow ring
 * marks one processed but empty. An unmarked past day has simply not been
 * looked at yet — it is still selectable and is fetched on demand. The three
 * states are drawn differently so "nothing happened" is never confused with
 * "nothing fetched".
 */

import { useMemo, useState } from 'react';
import { ChevronDownIcon } from './Icons';
import type { DayIndex } from '../api/client';

const WEEKDAYS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

function toIso(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

function monthLabel(year: number, month: number): string {
  // The grid is built from UTC dates, so it must be formatted in UTC too —
  // otherwise a UTC midnight lands in the previous month west of Greenwich.
  return new Intl.DateTimeFormat('en-US', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, month, 1)));
}

/** Monday-first offset of the 1st of the month. */
function leadingBlanks(year: number, month: number): number {
  const weekday = new Date(Date.UTC(year, month, 1)).getUTCDay();
  return (weekday + 6) % 7;
}

function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
}

interface CalendarProps {
  selected: string;
  today: string;
  index: Map<string, DayIndex>;
  onSelect: (date: string) => void;
  loading?: boolean;
}

export function Calendar({ selected, today, index, onSelect, loading }: CalendarProps) {
  const [year, month] = useMemo(() => {
    const [y, m] = selected.split('-').map(Number);
    return [y, (m ?? 1) - 1];
  }, [selected]);

  const [viewYear, setViewYear] = useState(year);
  const [viewMonth, setViewMonth] = useState(month);

  // Follow the selection when it moves into a different month.
  const [lastSelected, setLastSelected] = useState(selected);
  if (lastSelected !== selected) {
    setLastSelected(selected);
    setViewYear(year);
    setViewMonth(month);
  }

  const total = daysInMonth(viewYear, viewMonth);
  const blanks = leadingBlanks(viewYear, viewMonth);
  const cells: (string | null)[] = [
    ...Array.from({ length: blanks }, () => null),
    ...Array.from({ length: total }, (_, i) => toIso(viewYear, viewMonth, i + 1)),
  ];

  const step = (delta: number) => {
    const next = new Date(Date.UTC(viewYear, viewMonth + delta, 1));
    setViewYear(next.getUTCFullYear());
    setViewMonth(next.getUTCMonth());
  };

  const isFutureMonth = toIso(viewYear, viewMonth, 1) > today;

  return (
    <section className="mt-4 rounded-xl border border-slate-200" aria-label="Choose a day">
      <div className="flex items-center justify-between border-b border-slate-100 px-2 py-1.5">
        <button
          type="button"
          onClick={() => step(-1)}
          aria-label="Previous month"
          className="rounded-md p-1 text-slate-400 transition hover:bg-slate-50 hover:text-slate-700"
        >
          <ChevronDownIcon size={14} className="rotate-90" />
        </button>
        <h2 className="text-[12px] font-semibold text-slate-700" aria-live="polite">
          {monthLabel(viewYear, viewMonth)}
        </h2>
        <button
          type="button"
          onClick={() => step(1)}
          disabled={isFutureMonth}
          aria-label="Next month"
          className="rounded-md p-1 text-slate-400 transition hover:bg-slate-50 hover:text-slate-700 disabled:opacity-30 disabled:hover:bg-transparent"
        >
          <ChevronDownIcon size={14} className="-rotate-90" />
        </button>
      </div>

      <div className="px-2 pb-2 pt-1.5">
        <div className="grid grid-cols-7 gap-px" aria-hidden>
          {WEEKDAYS.map((day, i) => (
            <span
              key={`${day}-${i}`}
              className="pb-1 text-center text-[9.5px] font-medium uppercase text-slate-400"
            >
              {day}
            </span>
          ))}
        </div>

        <div className="grid grid-cols-7 gap-px" role="grid" data-testid="calendar-grid">
          {cells.map((iso, position) => {
            if (iso === null) return <span key={`blank-${position}`} />;

            const dayNumber = Number(iso.slice(-2));
            const record = index.get(iso);
            const isSelected = iso === selected;
            const isToday = iso === today;
            const isFuture = iso > today;

            return (
              <button
                key={iso}
                type="button"
                role="gridcell"
                aria-label={iso}
                aria-current={isSelected ? 'date' : undefined}
                aria-disabled={isFuture}
                disabled={isFuture || loading}
                data-testid={`calendar-day-${iso}`}
                onClick={() => onSelect(iso)}
                className={[
                  'relative flex h-7 flex-col items-center justify-center rounded-md text-[11.5px] transition',
                  isSelected
                    ? 'bg-blue-600 font-semibold text-white'
                    : isFuture
                      ? 'cursor-not-allowed text-slate-300'
                      : 'text-slate-600 hover:bg-slate-100',
                  isToday && !isSelected ? 'font-semibold text-blue-700' : '',
                ].join(' ')}
              >
                {dayNumber}
                {!isFuture && record?.stored ? (
                  <span
                    className={[
                      'absolute bottom-0.5 h-1 w-1 rounded-full border',
                      record.hasData
                        ? isSelected
                          ? 'border-white bg-white'
                          : 'border-emerald-500 bg-emerald-500'
                        : isSelected
                          ? 'border-white/70 bg-transparent'
                          : 'border-slate-300 bg-transparent',
                    ].join(' ')}
                    aria-hidden
                  />
                ) : null}
              </button>
            );
          })}
        </div>

        <p className="mt-2 flex items-center gap-2.5 px-0.5 text-[9.5px] text-slate-400">
          <span className="flex items-center gap-1">
            <span className="h-1 w-1 rounded-full bg-emerald-500" aria-hidden />
            has data
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1 w-1 rounded-full border border-slate-300" aria-hidden />
            empty
          </span>
          <span>unmarked = not fetched</span>
        </p>
      </div>
    </section>
  );
}
