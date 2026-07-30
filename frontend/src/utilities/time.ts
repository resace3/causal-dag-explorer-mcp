/**
 * Timezone-aware time helpers.
 *
 * Everything is formatted in the timeline's configured timezone rather than the
 * browser's, so the page always agrees with the day the backend reconstructed.
 */

const timeFormatters = new Map<string, Intl.DateTimeFormat>();
const partFormatters = new Map<string, Intl.DateTimeFormat>();

function timeFormatter(timeZone: string): Intl.DateTimeFormat {
  let formatter = timeFormatters.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone,
    });
    timeFormatters.set(timeZone, formatter);
  }
  return formatter;
}

function partFormatter(timeZone: string): Intl.DateTimeFormat {
  let formatter = partFormatters.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone,
    });
    partFormatters.set(timeZone, formatter);
  }
  return formatter;
}

export function toDate(value: Date | string | number): Date {
  return value instanceof Date ? value : new Date(value);
}

/** "7:15 AM" in the timeline's timezone. */
export function formatTime(value: Date | string, timeZone: string): string {
  return timeFormatter(timeZone).format(toDate(value)).replace(/ /g, ' ');
}

export function formatTimeRange(
  start: Date | string,
  end: Date | string | null | undefined,
  timeZone: string,
): string {
  const from = formatTime(start, timeZone);
  return end ? `${from} – ${formatTime(end, timeZone)}` : from;
}

/** Local wall-clock hour and minute for a moment, in the given timezone. */
export function wallClock(value: Date | string, timeZone: string): { hour: number; minute: number } {
  const parts = partFormatter(timeZone).formatToParts(toDate(value));
  const hour = Number(parts.find((part) => part.type === 'hour')?.value ?? '0');
  const minute = Number(parts.find((part) => part.type === 'minute')?.value ?? '0');
  return { hour: hour === 24 ? 0 : hour, minute };
}

export function formatDuration(minutes: number | null | undefined): string {
  if (minutes == null || Number.isNaN(minutes)) return '—';
  const total = Math.round(minutes);
  if (total < 60) return `${total} min`;
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

export function durationMinutes(
  start: Date | string,
  end: Date | string | null | undefined,
): number | null {
  if (!end) return null;
  return (toDate(end).getTime() - toDate(start).getTime()) / 60000;
}

/** "Sunday, July 27, 2026" for an ISO date string, without timezone drift. */
export function formatIsoDate(isoDate: string): string {
  const [year, month, day] = isoDate.split('-').map(Number);
  const date = new Date(Date.UTC(year, (month ?? 1) - 1, day ?? 1));
  return new Intl.DateTimeFormat('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(date);
}

export function formatRelativeToNow(value: string | null | undefined): string {
  if (!value) return 'never';
  const delta = Date.now() - toDate(value).getTime();
  if (delta < 60_000) return 'just now';
  const minutes = Math.round(delta / 60_000);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}
