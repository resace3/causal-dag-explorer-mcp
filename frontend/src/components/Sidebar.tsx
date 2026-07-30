/**
 * Narrow, quiet sidebar. Yesterday is the only navigation item — there is
 * nowhere else to go, by design.
 */

import { Calendar } from './Calendar';
import { SourcePicker } from './SourcePicker';
import { ClockIcon, HomeIcon, PlugIcon, PulseIcon, WatchIcon } from './Icons';
import type { DayIndex } from '../api/client';
import type { DataSource, DataSourceReport, SourceStatus } from '../types/timeline';
import { formatRelativeToNow } from '../utilities/time';

const STATUS_LABELS: Record<SourceStatus, string> = {
  connected: 'Connected',
  disconnected: 'Disconnected',
  syncing: 'Syncing',
  error: 'Error',
  mock_data: 'Mock data',
};

const STATUS_STYLES: Record<SourceStatus, { dot: string; text: string }> = {
  connected: { dot: 'bg-emerald-500', text: 'text-emerald-700' },
  disconnected: { dot: 'bg-slate-300', text: 'text-slate-500' },
  syncing: { dot: 'bg-sky-500 animate-pulse', text: 'text-sky-700' },
  error: { dot: 'bg-rose-500', text: 'text-rose-700' },
  mock_data: { dot: 'bg-amber-400', text: 'text-amber-700' },
};

const TRANSPORT_LABELS: Record<string, string> = {
  mcp: 'read over MCP',
  rest: 'read over its REST API',
  mock: 'generated locally',
  file: 'read from a file export',
};

function sourceIcon(source: DataSource) {
  if (source.id === 'home_assistant') return HomeIcon;
  if (source.transport === 'mcp') return PlugIcon;
  return WatchIcon;
}

function SourceRow({ source }: { source: DataSource }) {
  const status = STATUS_STYLES[source.status] ?? STATUS_STYLES.disconnected;
  const Icon = sourceIcon(source);
  const idle = source.status === 'connected' && !source.hasData;

  return (
    <li className="px-3 py-2.5" data-testid={`source-${source.id}`}>
      <div className="flex items-center gap-2.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-50 text-slate-500">
          <Icon size={16} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12.5px] font-medium text-slate-700">
            {source.name}
          </span>
          <span className={`flex items-center gap-1.5 text-[11px] ${idle ? 'text-slate-500' : status.text}`}>
            <span
              className={`h-1.5 w-1.5 shrink-0 rounded-full ${idle ? 'bg-slate-300' : status.dot}`}
              aria-hidden
            />
            {STATUS_LABELS[source.status] ?? source.status}
            {idle ? ' · no data yesterday' : ''}
          </span>
        </span>
      </div>

      {/* Which MCP server this row corresponds to, and how it is reached. */}
      {source.mcpServer ? (
        <p className="mt-1.5 pl-[38px] text-[10.5px] leading-snug text-slate-400">
          <code className="rounded bg-slate-50 px-1 py-px font-mono text-[10px] text-slate-500">
            {source.mcpServer}
          </code>
          <span className="ml-1.5">{TRANSPORT_LABELS[source.transport] ?? source.transport}</span>
        </p>
      ) : null}

      {/*
        Only failures explain themselves here. When a source is working, its
        connection string and route list are noise in a panel meant to answer
        one question: is this source up?
      */}
      {source.status === 'error' && source.detail ? (
        <p className="mt-1 break-words pl-[38px] text-[10.5px] leading-snug text-rose-600">
          {source.detail}
        </p>
      ) : null}
    </li>
  );
}

interface SidebarProps {
  sources: DataSourceReport | null;
  state?: 'checking' | 'ready' | 'unavailable';
  lastSync: string | null | undefined;
  selectedDate: string | null;
  yesterday: string | null;
  today: string | null;
  dayIndex: Map<string, DayIndex>;
  onSelectDate: (date: string) => void;
  loadingDay?: boolean;
  /** Fires after the MCP selection changes, so the day is rebuilt from it. */
  onSourcesChanged?: () => void;
}

export function Sidebar({
  sources,
  onSourcesChanged = () => {},
  state = 'ready',
  lastSync,
  selectedDate,
  yesterday,
  today,
  dayIndex,
  onSelectDate,
  loadingDay,
}: SidebarProps) {
  const onYesterday = selectedDate !== null && selectedDate === yesterday;
  return (
    <aside
      className="flex w-[228px] shrink-0 flex-col border-r border-slate-200 bg-white px-4 py-6"
      aria-label="Primary"
    >
      <nav aria-label="Main navigation">
        <ul className="space-y-1">
          <li>
            <button
              type="button"
              aria-current={onYesterday ? 'page' : undefined}
              data-testid="nav-yesterday"
              onClick={() => yesterday && onSelectDate(yesterday)}
              className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-[14px] font-semibold transition ${
                onYesterday
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-800'
              }`}
            >
              <PulseIcon size={19} />
              Yesterday
            </button>
          </li>
        </ul>
      </nav>

      {selectedDate && today ? (
        <Calendar
          selected={selectedDate}
          today={today}
          index={dayIndex}
          onSelect={onSelectDate}
          loading={loadingDay}
        />
      ) : null}

      <section className="mt-4 rounded-xl border border-slate-200" aria-label="MCPs">
        <h2 className="border-b border-slate-100 px-3 py-2.5 text-[12.5px] font-semibold text-slate-700">
          MCPs
        </h2>
        <SourcePicker onChanged={onSourcesChanged} />
        {sources ? (
          <ul className="divide-y divide-slate-100">
            {sources.sources.map((source) => (
              <SourceRow key={source.id} source={source} />
            ))}
          </ul>
        ) : state === 'checking' ? (
          <p className="px-3 py-3 text-[11.5px] text-slate-400">
            Checking sources… signing in to an MCP server can take a moment.
          </p>
        ) : (
          <p className="px-3 py-3 text-[11.5px] text-slate-400">
            Source status is unavailable — the local API did not respond.
          </p>
        )}
        {lastSync ? (
          <p className="border-t border-slate-100 px-3 py-2 text-[10.5px] text-slate-400">
            Last sync {formatRelativeToNow(lastSync)}
          </p>
        ) : null}
      </section>

      <div className="mt-auto pt-8">
        <p className="flex items-start gap-2 rounded-lg border border-slate-200 px-3 py-2.5 text-[11.5px] leading-snug text-slate-500">
          <ClockIcon size={15} className="mt-px shrink-0 text-slate-400" />
          All times shown in your local time
        </p>
      </div>
    </aside>
  );
}
