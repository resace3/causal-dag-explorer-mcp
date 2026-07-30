/**
 * The "+" beneath the timeline, and the box for describing a new row.
 *
 * The reader behind this runs locally and is rule-based — it matches stream
 * names and thresholds against the streams the day actually holds. That makes
 * it fallible in a specific way: it can match something *near* what was asked
 * for. So it never creates anything without first showing what it understood,
 * and **Add** stays disabled until there is a reading to agree with. A row
 * built on a misreading is worse than one that was never created.
 *
 * The assistant you are already talking to can add rows too, with real language
 * understanding, through the `add_timeline_row` MCP tool.
 */

import { useEffect, useRef, useState } from 'react';
import { api, type RowInterpretation } from '../api/client';
import { CheckIcon, InfoIcon } from '../components/Icons';

/** Concrete enough to copy, varied enough to show the shape of what works. */
const EXAMPLES = [
  'heart rate above 100',
  'heart rate below 50',
  'step rate over 60',
  'sleep',
  'when I was away from home',
];

interface AddRowProps {
  date: string | null;
  onAdded: () => void;
}

export function AddRow({ date, onAdded }: AddRowProps) {
  const [open, setOpen] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [reading, setReading] = useState<RowInterpretation | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement | null>(null);
  const request = useRef(0);

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  // Read the request as it is typed, but only after a pause: a call per
  // keystroke would show a reading of half a word.
  useEffect(() => {
    const text = prompt.trim();
    if (!text) {
      setReading(null);
      setChecking(false);
      return undefined;
    }
    setChecking(true);
    const id = (request.current += 1);
    const timer = window.setTimeout(() => {
      void api
        .interpretRow(text, date)
        .then((result) => {
          if (id === request.current) setReading(result);
        })
        .catch(() => {
          if (id === request.current) setReading(null);
        })
        .finally(() => {
          if (id === request.current) setChecking(false);
        });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [prompt, date]);

  const close = () => {
    setOpen(false);
    setPrompt('');
    setReading(null);
    setError(null);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!reading?.understood) return;
    setBusy(true);
    setError(null);
    try {
      await api.addRow(prompt.trim(), date);
      onAdded();
      close();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid="add-row-open"
        className="group flex w-full items-center gap-2 border-t border-dashed border-slate-200 px-5 py-3 text-[12.5px] font-medium text-slate-400 transition hover:bg-slate-50 hover:text-slate-600"
      >
        <span className="flex h-5 w-5 items-center justify-center rounded-md border border-dashed border-slate-300 text-[15px] leading-none text-slate-400 transition group-hover:border-slate-400 group-hover:text-slate-600">
          +
        </span>
        Add a row
      </button>
    );
  }

  return (
    <form
      onSubmit={submit}
      data-testid="add-row-form"
      className="border-t border-slate-200 bg-slate-50/70 px-5 py-4"
    >
      <label className="block text-[11px] font-semibold uppercase tracking-[0.07em] text-slate-500">
        Describe the row
      </label>
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        <input
          ref={input}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') close();
          }}
          placeholder="e.g. heart rate above 100"
          data-testid="add-row-prompt"
          className="min-w-[240px] flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-slate-700 focus:border-slate-400 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!reading?.understood || busy}
          data-testid="add-row-submit"
          className="flex items-center gap-1.5 rounded-lg bg-slate-800 px-3.5 py-2 text-[12.5px] font-medium text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <CheckIcon size={14} />
          Add row
        </button>
        <button
          type="button"
          onClick={close}
          data-testid="add-row-cancel"
          className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-[12.5px] font-medium text-slate-500 transition hover:text-slate-700"
        >
          Cancel
        </button>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] text-slate-400">Try:</span>
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => setPrompt(example)}
            data-testid={`add-row-example-${example.replace(/\s+/g, '-')}`}
            className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11.5px] text-slate-500 transition hover:border-slate-300 hover:text-slate-700"
          >
            {example}
          </button>
        ))}
      </div>

      {/* Nothing is created until this says something the user agrees with. */}
      <div className="mt-2.5 min-h-[34px]" aria-live="polite" data-testid="add-row-reading">
        {checking ? (
          <p className="text-[12px] text-slate-400">Reading…</p>
        ) : reading?.understood ? (
          <p className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12.5px] text-emerald-900">
            <CheckIcon size={14} className="shrink-0" />
            <span>
              Understood as <strong className="font-semibold">{reading.summary}</strong>
            </span>
          </p>
        ) : reading ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12.5px] leading-relaxed text-amber-900">
            <p className="flex items-start gap-2">
              <InfoIcon size={14} className="mt-0.5 shrink-0" />
              <span>{reading.problem}</span>
            </p>
            {reading.known.length ? (
              <p className="mt-1.5 pl-6 text-[11.5px] text-amber-800">
                On this day: {reading.known.join(', ')}.
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-[11.5px] leading-relaxed text-slate-400">
            Name a stream, optionally with a threshold. Read on this machine — the request
            is not sent anywhere.
          </p>
        )}
      </div>

      {error ? (
        <p role="alert" className="mt-2 text-[12px] text-rose-700">
          {error}
        </p>
      ) : null}
    </form>
  );
}
