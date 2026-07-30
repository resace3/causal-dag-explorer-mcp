/**
 * Choosing which MCP integrations the timeline reads from, and in what order.
 *
 * Order is not decoration: when two sources both offer a metric, the one higher
 * in the list supplies it. Metrics are never blended between sources, so a
 * heart-rate line always comes from one device rather than being stitched
 * together from two — which is why this is a ranked list rather than a set of
 * checkboxes.
 *
 * Switching a source off means it is not contacted at all, not that its data is
 * hidden. The status panel says "switched off" rather than reporting a
 * connection that was never attempted.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type SourceOption } from '../api/client';
import { ChevronDownIcon, ChevronUpIcon, PlugIcon } from './Icons';

interface SourcePickerProps {
  /** Called after a change, so the timeline and status refetch. */
  onChanged: () => void;
}

export function SourcePicker({ onChanged }: SourcePickerProps) {
  const [open, setOpen] = useState(false);
  const [available, setAvailable] = useState<SourceOption[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const container = useRef<HTMLDivElement | null>(null);

  const load = useCallback(() => {
    void api
      .sourceSelection()
      .then((response) => {
        setAvailable(response.available);
        setSelected(response.selected);
      })
      .catch(() => setAvailable([]));
  }, []);

  useEffect(load, [load]);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
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

  const apply = async (next: string[]) => {
    setBusy(true);
    setError(null);
    const previous = selected;
    setSelected(next);
    try {
      const response = await api.setSourceSelection(next);
      setSelected(response.selected);
      onChanged();
    } catch (cause) {
      setSelected(previous); // the server refused; do not show a state it rejected
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (id: string) => {
    const next = selected.includes(id)
      ? selected.filter((item) => item !== id)
      : [...selected, id];
    if (next.length === 0) {
      setError('At least one source has to stay switched on.');
      return;
    }
    void apply(next);
  };

  const move = (id: string, direction: -1 | 1) => {
    const from = selected.indexOf(id);
    const to = from + direction;
    if (from === -1 || to < 0 || to >= selected.length) return;
    const next = [...selected];
    next.splice(to, 0, ...next.splice(from, 1));
    void apply(next);
  };

  if (available.length === 0) return null;

  const ordered = [
    ...selected
      .map((id) => available.find((item) => item.id === id))
      .filter((item): item is SourceOption => Boolean(item)),
    ...available.filter((item) => !selected.includes(item.id)),
  ];

  return (
    <div className="relative border-b border-slate-100 px-3 py-2" ref={container}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="true"
        data-testid="source-picker-toggle"
        className="flex w-full items-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[11.5px] font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-800"
      >
        <PlugIcon size={13} />
        <span className="flex-1 text-left">Reading from</span>
        <span className="text-slate-400">
          {selected.length}/{available.length}
        </span>
        <ChevronDownIcon size={13} />
      </button>

      {open ? (
        <div
          role="group"
          aria-label="MCP integrations to read from"
          data-testid="source-picker-popover"
          // Wider than the sidebar and allowed to overflow it: inside 250px
          // the source descriptions truncate to "Sleep, he…", which defeats
          // the point of listing what each one contributes.
          className="absolute left-3 z-30 mt-1.5 w-[290px] rounded-xl border border-slate-200 bg-white p-2 shadow-lg shadow-slate-200/60"
        >
          <p className="px-1 pb-1.5 text-[10.5px] leading-snug text-slate-400">
            When two sources both have a metric, the higher one supplies it. Metrics are
            never blended between sources.
          </p>

          {ordered.map((item) => {
            const on = selected.includes(item.id);
            const rank = selected.indexOf(item.id);
            return (
              <div
                key={item.id}
                data-testid={`source-option-${item.id}`}
                className="flex items-start gap-2 rounded-lg px-1.5 py-1.5 hover:bg-slate-50"
              >
                <input
                  type="checkbox"
                  checked={on}
                  disabled={busy}
                  onChange={() => toggle(item.id)}
                  aria-label={item.name}
                  data-testid={`source-toggle-${item.id}`}
                  className="mt-0.5 h-3.5 w-3.5 shrink-0 rounded border-slate-300"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    {on ? (
                      <span className="rounded bg-slate-100 px-1 text-[10px] font-semibold text-slate-500">
                        {rank + 1}
                      </span>
                    ) : null}
                    <span
                      className={`truncate text-[12px] font-medium ${
                        on ? 'text-slate-700' : 'text-slate-400'
                      }`}
                    >
                      {item.name}
                    </span>
                  </span>
                  <span className="mt-0.5 block text-[10.5px] leading-snug text-slate-400">
                    <code className="rounded bg-slate-100 px-1 text-[9.5px]">
                      {item.mcpServer ?? 'local'}
                    </code>{' '}
                    {item.provides.join(' · ')}
                  </span>
                </span>

                {on && selected.length > 1 ? (
                  <span className="flex shrink-0 flex-col">
                    <button
                      type="button"
                      disabled={busy || rank === 0}
                      onClick={() => move(item.id, -1)}
                      aria-label={`Give ${item.name} higher priority`}
                      data-testid={`source-up-${item.id}`}
                      className="rounded text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-20"
                    >
                      <ChevronUpIcon size={12} />
                    </button>
                    <button
                      type="button"
                      disabled={busy || rank === selected.length - 1}
                      onClick={() => move(item.id, 1)}
                      aria-label={`Give ${item.name} lower priority`}
                      data-testid={`source-down-${item.id}`}
                      className="rounded text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-20"
                    >
                      <ChevronDownIcon size={12} />
                    </button>
                  </span>
                ) : null}
              </div>
            );
          })}

          {error ? (
            <p role="alert" className="mt-1 px-1.5 text-[11px] leading-snug text-rose-700">
              {error}
            </p>
          ) : (
            <p className="mt-1 border-t border-slate-100 px-1.5 pt-1.5 text-[10.5px] leading-snug text-slate-400">
              A source switched off is not contacted at all. Refresh to rebuild the day.
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}
