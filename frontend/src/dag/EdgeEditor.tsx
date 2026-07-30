/**
 * The list behind the canvas: every arrow in the model, with removal and
 * restore. Arrows are *drawn* by dragging between rows on the graph itself;
 * this is the ledger of what that has produced.
 *
 * The knowledge base is a published prior, not gospel — you may know something
 * about yourself no paper does. What the editor will not do is let the two
 * blur together: an arrow you drew is labelled as yours everywhere it appears,
 * and removing a published one suppresses it so it can be restored rather than
 * quietly deleting it.
 *
 * Adding an arrow that would make the graph cyclic is refused by the server,
 * and the reason is shown here rather than swallowed.
 */

import { useCallback, useEffect, useState } from 'react';
import { api, type CausalEdgeRow, type CausalEdgesResponse } from '../api/client';
import { CloseIcon, RefreshIcon } from '../components/Icons';

interface EdgeEditorProps {
  /** Called after any successful change, so the graph refetches. */
  onChanged: () => void;
}

export function EdgeEditor({ onChanged }: EdgeEditorProps) {
  const [data, setData] = useState<CausalEdgesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState('');

  const load = useCallback(() => {
    void api
      .causalEdges()
      .then(setData)
      .catch((cause) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, []);

  useEffect(load, [load]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      load();
      onChanged();
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const shown = (data?.edges ?? []).filter((edge) => {
    if (!filter.trim()) return true;
    const needle = filter.toLowerCase();
    return (
      edge.sourceLabel.toLowerCase().includes(needle) ||
      edge.targetLabel.toLowerCase().includes(needle)
    );
  });
  const mine = shown.filter((edge) => edge.origin === 'user');
  const published = shown.filter((edge) => edge.origin === 'knowledge_base');

  return (
    <div
      className="border-t border-slate-100 bg-slate-50/60 px-5 py-4"
      data-testid="dag-edge-editor"
    >

      {error ? (
        <p
          role="alert"
          data-testid="edge-error"
          className="mt-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] leading-relaxed text-rose-800"
        >
          {error}
        </p>
      ) : null}

      {data?.suppressed.length ? (
        <div className="mt-3">
          <h4 className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.07em] text-slate-400">
            Removed from the published model
          </h4>
          <ul className="flex flex-wrap gap-2">
            {data.suppressed.map((edge) => (
              <li
                key={`${edge.source}->${edge.target}`}
                className="flex items-center gap-2 rounded-lg border border-dashed border-slate-300 bg-white px-2.5 py-1 text-[11.5px] text-slate-500"
              >
                <span className="line-through">
                  {edge.sourceLabel} → {edge.targetLabel}
                </span>
                <button
                  type="button"
                  disabled={busy}
                  data-testid={`edge-restore-${edge.source}-${edge.target}`}
                  onClick={() => void run(() => api.restoreCausalEdge(edge.source, edge.target))}
                  className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium text-slate-600 transition hover:bg-slate-100"
                >
                  <RefreshIcon size={12} />
                  Restore
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-3 flex items-center justify-between gap-3">
        <h4 className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-slate-400">
          Arrows in the model ({data?.edges.length ?? 0})
        </h4>
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter by variable…"
          data-testid="edge-filter"
          className="w-52 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[12px] text-slate-700"
        />
      </div>

      <div className="mt-2 max-h-64 overflow-y-auto rounded-lg border border-slate-200 bg-white">
        {mine.length ? (
          <EdgeGroup
            title="Added by you"
            edges={mine}
            busy={busy}
            onRemove={(edge) => void run(() => api.removeCausalEdge(edge.source, edge.target))}
          />
        ) : null}
        <EdgeGroup
          title="From published physiology"
          edges={published}
          busy={busy}
          onRemove={(edge) => void run(() => api.removeCausalEdge(edge.source, edge.target))}
        />
        {shown.length === 0 ? (
          <p className="px-3 py-4 text-center text-[12px] text-slate-400">
            No arrow matches “{filter}”.
          </p>
        ) : null}
      </div>
    </div>
  );
}

function EdgeGroup({
  title,
  edges,
  busy,
  onRemove,
}: {
  title: string;
  edges: CausalEdgeRow[];
  busy: boolean;
  onRemove: (edge: CausalEdgeRow) => void;
}) {
  if (!edges.length) return null;
  return (
    <>
      <p className="sticky top-0 border-b border-slate-100 bg-slate-50 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-400">
        {title}
      </p>
      <ul>
        {edges.map((edge) => (
          <li
            key={`${edge.source}->${edge.target}`}
            data-testid={`edge-row-${edge.source}-${edge.target}`}
            className="flex items-start gap-2 border-b border-slate-50 px-3 py-1.5 last:border-b-0"
          >
            <span className="min-w-0 flex-1">
              <span className="block text-[12px] text-slate-700">
                {edge.sourceLabel} <span className="text-slate-400">→</span> {edge.targetLabel}
                {edge.origin === 'user' ? (
                  <span className="ml-1.5 rounded bg-violet-100 px-1.5 py-px text-[10px] font-medium text-violet-700">
                    yours
                  </span>
                ) : null}
              </span>
              {edge.rationale ? (
                <span className="mt-0.5 block text-[11px] leading-snug text-slate-400">
                  {edge.rationale}
                </span>
              ) : null}
            </span>
            <span className="shrink-0 pt-0.5 text-[10.5px] text-slate-400">{edge.strength}</span>
            <button
              type="button"
              disabled={busy}
              aria-label={`Remove ${edge.sourceLabel} to ${edge.targetLabel}`}
              data-testid={`edge-remove-${edge.source}-${edge.target}`}
              onClick={() => onRemove(edge)}
              className="shrink-0 rounded p-1 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600 disabled:opacity-40"
            >
              <CloseIcon size={13} />
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
