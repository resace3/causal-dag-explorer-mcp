/**
 * Controls above the timeline: view mode, visible data streams, zoom, refresh.
 * Nothing here is a placeholder for a future feature.
 */

import { useEffect, useRef, useState } from 'react';
import { ChevronDownIcon, LayersIcon, RefreshIcon } from './Icons';
import type { Lane } from '../types/timeline';
import { accentTheme } from '../utilities/lanes';

export type ViewMode = 'expanded' | 'collapsed' | 'dag';

interface StreamVisibilityProps {
  lanes: Lane[];
  hidden: Set<string>;
  onToggle: (laneId: string) => void;
}

function StreamVisibility({ lanes, hidden, onToggle }: StreamVisibilityProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const available = lanes.filter((lane) => lane.available);
  const unavailable = lanes.filter((lane) => !lane.available);
  const visibleCount = available.filter((lane) => !hidden.has(lane.id)).length;

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="true"
        data-testid="stream-visibility-toggle"
        className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12.5px] font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800"
      >
        <LayersIcon size={15} />
        Visible data streams
        <span className="text-slate-400">
          {visibleCount}/{available.length}
        </span>
        <ChevronDownIcon size={14} />
      </button>

      {open ? (
        <div
          role="group"
          aria-label="Visible data streams"
          data-testid="stream-visibility-popover"
          className="absolute right-0 z-30 mt-2 w-72 rounded-xl border border-slate-200 bg-white p-2 shadow-lg shadow-slate-200/60"
        >
          {available.map((lane) => {
            const theme = accentTheme(lane.accent);
            const checked = !hidden.has(lane.id);
            return (
              <label
                key={lane.id}
                className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-slate-50"
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggle(lane.id)}
                  className="h-3.5 w-3.5 rounded border-slate-300"
                  style={{ accentColor: theme.stroke }}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12.5px] text-slate-700">{lane.label}</span>
                  <span className="block truncate text-[11px] text-slate-400">
                    {lane.events.length} events
                    {lane.series.length
                      ? ` · ${lane.series.reduce((total, s) => total + s.points.length, 0)} samples`
                      : ''}
                  </span>
                </span>
              </label>
            );
          })}

          {unavailable.length ? (
            <div className="mt-1.5 border-t border-slate-100 pt-2">
              <p className="px-2 pb-1 text-[10.5px] font-semibold uppercase tracking-wide text-slate-400">
                No data yesterday
              </p>
              {unavailable.map((lane) => (
                <p key={lane.id} className="px-2 py-1 text-[11px] leading-snug text-slate-400">
                  <span className="font-medium text-slate-500">{lane.label}</span> —{' '}
                  {lane.unavailableReason}
                </p>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

interface TimelineControlsProps {
  lanes: Lane[];
  hidden: Set<string>;
  onToggleLane: (laneId: string) => void;
  mode: ViewMode;
  onModeChange: (mode: ViewMode) => void;
  zoom: number;
  onZoomChange: (zoom: number) => void;
  onRefresh: () => void;
  refreshing: boolean;
}

const ZOOM_STEPS = [1, 1.5, 2, 3];

export function TimelineControls({
  lanes,
  hidden,
  onToggleLane,
  mode,
  onModeChange,
  zoom,
  onZoomChange,
  onRefresh,
  refreshing,
}: TimelineControlsProps) {
  const zoomIndex = ZOOM_STEPS.indexOf(zoom);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
      <div
        className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5"
        role="group"
        aria-label="Timeline detail"
      >
        {(['expanded', 'collapsed', 'dag'] as ViewMode[]).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={mode === value}
            data-testid={`mode-${value}`}
            onClick={() => onModeChange(value)}
            className={`rounded-[6px] px-3 py-1.5 text-[12.5px] font-medium capitalize transition ${
              mode === value
                ? 'bg-white text-slate-800 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {value === 'dag' ? 'DAG' : value}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {mode !== 'dag' ? (
        <div className="flex items-center gap-1 rounded-lg border border-slate-200 px-1 py-0.5">
          <button
            type="button"
            aria-label="Zoom out"
            disabled={zoomIndex <= 0}
            onClick={() => onZoomChange(ZOOM_STEPS[Math.max(0, zoomIndex - 1)])}
            className="rounded px-2 py-1 text-[13px] text-slate-500 transition hover:bg-slate-50 disabled:opacity-40"
          >
            −
          </button>
          <span className="min-w-[34px] text-center text-[11.5px] text-slate-500">{zoom}×</span>
          <button
            type="button"
            aria-label="Zoom in"
            disabled={zoomIndex >= ZOOM_STEPS.length - 1}
            onClick={() => onZoomChange(ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, zoomIndex + 1)])}
            className="rounded px-2 py-1 text-[13px] text-slate-500 transition hover:bg-slate-50 disabled:opacity-40"
          >
            +
          </button>
        </div>
        ) : null}

        {mode === 'expanded' ? (
          <StreamVisibility lanes={lanes} hidden={hidden} onToggle={onToggleLane} />
        ) : null}

        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          data-testid="refresh-button"
          className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-[12.5px] font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800 disabled:opacity-60"
        >
          <RefreshIcon size={14} className={refreshing ? 'animate-spin' : undefined} />
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
    </div>
  );
}
