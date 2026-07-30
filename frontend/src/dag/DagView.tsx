/**
 * The DAG tab: an expected causal structure, laid out on the day's own clock.
 *
 * Two things are being shown at once, and they have very different standing:
 *
 *   * **The nodes are observations.** Each one sits at the hour the day
 *     actually recorded that event or state, on the same x-scale the timeline
 *     tab uses, so the two views line up exactly.
 *   * **The arrows are assumptions.** They come from published physiology, not
 *     from this data. Nothing here has been estimated or tested.
 *
 * Grounding the graph in real times buys one piece of discipline — an arrow is
 * only drawn between things whose order in time permits it — and costs the
 * ability to draw anything for a variable the day never recorded. Those are
 * listed rather than dropped, because an arrow silently failing to appear would
 * read as evidence of absence.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  api,
  type DagLink,
  type DagOccurrence,
  type DagResponse,
  type DagRow,
  type DagVariable,
} from '../api/client';
import { useElementWidth } from '../hooks/useElementWidth';
import { VariableIcon } from '../components/Icons';
import { EdgeEditor } from './EdgeEditor';
import { AxisRow, GridLines } from '../timeline/Axis';
import { PAD_LEFT, createScale } from '../timeline/scale';
import { AXIS_HEIGHT, LANE_LABEL_WIDTH } from '../utilities/lanes';
import { formatTime } from '../utilities/time';

const ROW_HEIGHT = 86;
const NODE_RADIUS = 20;
/** Kept at 0.6 × the node's diameter, so the glyph fills it the same way. */
const ICON_SIZE = Math.round(NODE_RADIUS * 1.2);
const BAR_HEIGHT = 10;
const MIN_PLOT_WIDTH = 620;
/** Below this gap two captions would collide, so the later one is dropped. */
const LABEL_GAP = 80;

const IMMEDIATE_COLOR = '#1e3a8a';
const DELAYED_COLOR = '#16a34a';
const USER_EDGE_COLOR = '#7c3aed';

interface RoleStyle {
  /** Pale wash, for bands and legend swatches. */
  fill: string;
  stroke: string;
  /** Saturated enough to carry a white icon — never a pale tint. */
  solid: string;
  text: string;
  label: string;
}

const ROLE_STYLES: Record<string, RoleStyle> = {
  exposure: {
    fill: '#dcfce7',
    stroke: '#16a34a',
    solid: '#16a34a',
    text: '#14532d',
    label: 'Exposure',
  },
  outcome: {
    fill: '#dbeafe',
    stroke: '#2563eb',
    solid: '#2563eb',
    text: '#1e3a8a',
    label: 'Outcome',
  },
  confounder: {
    fill: '#fef3c7',
    stroke: '#d97706',
    solid: '#d97706',
    text: '#78350f',
    label: 'Confounder',
  },
  mediator: {
    fill: '#ede9fe',
    stroke: '#7c3aed',
    solid: '#7c3aed',
    text: '#4c1d95',
    label: 'Mediator',
  },
  collider: {
    fill: '#ffe4e6',
    stroke: '#e11d48',
    solid: '#e11d48',
    text: '#881337',
    label: 'Collider',
  },
  'direct cause': {
    fill: '#f1f5f9',
    stroke: '#64748b',
    solid: '#475569',
    text: '#334155',
    label: 'Direct cause',
  },
  context: {
    fill: '#f1f5f9',
    stroke: '#94a3b8',
    solid: '#64748b',
    text: '#475569',
    label: 'Context',
  },
};

/**
 * Background material is drawn as an outline rather than a solid, so the nodes
 * that carry a role in the analysis stay the ones that catch the eye. Without
 * this, "context" and "direct cause" are two slates nobody can tell apart.
 */
const OUTLINED_ROLES = new Set(['context']);

/** Weaker evidence for a link must not be drawn like stronger evidence. */
const STRENGTH_STYLES: Record<string, { width: number; opacity: number; label: string }> = {
  established: { width: 1.9, opacity: 1, label: 'well established' },
  plausible: { width: 1.6, opacity: 0.78, label: 'plausible' },
  speculative: { width: 1.2, opacity: 0.55, label: 'speculative' },
};

function roleStyle(role: string) {
  return ROLE_STYLES[role] ?? ROLE_STYLES.context;
}

function strengthStyle(strength: string) {
  return STRENGTH_STYLES[strength] ?? STRENGTH_STYLES.plausible;
}

/** "7 AM" on the hour, "11:19 AM" otherwise — the reference-style compact label. */
function compactTime(value: string, timeZone: string): string {
  return formatTime(value, timeZone).replace(':00', '');
}

function formatLag(minutes: number): string {
  if (minutes < 1) return 'no gap';
  if (minutes < 60) return `${Math.round(minutes)} min later`;
  const hours = minutes / 60;
  return `${hours >= 10 ? Math.round(hours) : hours.toFixed(1)} h later`;
}

function VariableSelect({
  label,
  value,
  variables,
  onChange,
  allowNone,
  testId,
}: {
  label: string;
  value: string;
  variables: DagVariable[];
  onChange: (value: string) => void;
  allowNone?: boolean;
  testId: string;
}) {
  return (
    <label className="flex items-center gap-2 text-[12.5px] text-slate-600">
      {label}
      <select
        value={value}
        data-testid={testId}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[12.5px] text-slate-700 transition hover:border-slate-300"
      >
        {allowNone ? <option value="">— none —</option> : null}
        {variables.map((item) => (
          <option key={item.id} value={item.id}>
            {item.label}
            {item.measured ? '' : ' (unmeasured)'}
          </option>
        ))}
      </select>
    </label>
  );
}

function RowLabel({ row }: { row: DagRow }) {
  const style = roleStyle(row.role);
  return (
    <div
      className="flex items-center gap-2.5 border-b border-slate-100 px-5"
      style={{ height: ROW_HEIGHT }}
      data-testid={`dag-row-${row.variable}`}
    >
      <span
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
        style={{ backgroundColor: style.fill, color: style.solid }}
        aria-hidden
      >
        <VariableIcon variable={row.variable} size={17} />
      </span>
      <span className="min-w-0">
        <span
          className="block truncate text-[13px] font-semibold leading-tight"
          style={{ color: style.text }}
        >
          {row.label}
        </span>
        <span className="mt-0.5 block truncate text-[11px] leading-tight text-slate-500">
          {style.label}
          {row.unit ? ` · ${row.unit}` : ''}
        </span>
      </span>
    </div>
  );
}

export function DagView({ date }: { date: string | null }) {
  const [variables, setVariables] = useState<DagVariable[]>([]);
  const [outcome, setOutcome] = useState('sleep_duration');
  const [exposure, setExposure] = useState('');
  const [dag, setDag] = useState<DagResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [hovered, setHovered] = useState<DagLink | null>(null);
  const [selected, setSelected] = useState<DagOccurrence | null>(null);
  const [editing, setEditing] = useState(false);
  // Bumped by the editor so an added or removed arrow rebuilds the graph.
  const [edgeRevision, setEdgeRevision] = useState(0);
  // A connection being dragged out of a node, and where the pointer is now.
  const [connect, setConnect] = useState<{ from: string; x: number; y: number } | null>(null);
  const [pointer, setPointer] = useState<{ x: number; y: number } | null>(null);
  const [hoverRow, setHoverRow] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const { ref, width } = useElementWidth<HTMLDivElement>(900);
  const requestId = useRef(0);

  useEffect(() => {
    if (!date) return;
    void api
      .dagVariables(date)
      .then((response) => setVariables(response.variables))
      .catch(() => setVariables([]));
  }, [date]);

  useEffect(() => {
    if (!date) return;
    const id = (requestId.current += 1);
    setBusy(true);
    void api
      .dag({ outcome, exposure: exposure || null, day: date })
      .then((response) => {
        if (id !== requestId.current) return;
        setDag(response);
        setSelected(null);
        setError(null);
      })
      .catch((cause) => {
        if (id !== requestId.current) return;
        setDag(null);
        setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (id === requestId.current) setBusy(false);
      });
  }, [date, outcome, exposure, edgeRevision]);

  const placed = dag?.timeline ?? null;
  const plotWidth = Math.max(width, MIN_PLOT_WIDTH);

  const scale = useMemo(
    () =>
      placed
        ? createScale(placed.dayStart, placed.dayEnd, plotWidth, placed.localTimezone)
        : null,
    [placed, plotWidth],
  );

  /**
   * Rows the day can actually draw, kept in the backend's cause-first order.
   *
   * While editing, every variable in the graph gets a row even when the day
   * recorded nothing for it — otherwise there would be no way to draw an arrow
   * to stress or work schedule, which are exactly the ones worth adding. In
   * view mode the original rule holds: a row appears only when the day has
   * something to put on it.
   */
  const rows = useMemo(() => {
    if (!placed) return [];
    if (editing) return placed.rows;
    const withData = new Set(placed.occurrences.map((item) => item.variable));
    return placed.rows.filter((row) => withData.has(row.variable));
  }, [placed, editing]);

  const rowIndex = useMemo(
    () => new Map(rows.map((row, index) => [row.variable, index])),
    [rows],
  );

  const geometry = useMemo(() => {
    if (!scale || !placed) return { nodes: [], byId: new Map<string, PlacedNode>() };
    const nodes: PlacedNode[] = [];
    for (const occurrence of placed.occurrences) {
      const index = rowIndex.get(occurrence.variable);
      if (index === undefined) continue;
      const x = scale.x(occurrence.start);
      const xEnd = occurrence.end ? Math.max(scale.x(occurrence.end), x + 2) : x;
      nodes.push({
        occurrence,
        x,
        xEnd,
        y: index * ROW_HEIGHT + ROW_HEIGHT / 2,
        role: rows[index].role,
      });
    }
    return { nodes, byId: new Map(nodes.map((node) => [node.occurrence.id, node])) };
  }, [scale, placed, rowIndex, rows]);

  /** Where the pointer is, in the SVG's own coordinates. */
  const toSvgPoint = useCallback((event: { clientX: number; clientY: number }) => {
    const box = svgRef.current?.getBoundingClientRect();
    if (!box) return null;
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  }, []);

  const startConnect = useCallback(
    (variable: string, x: number, y: number) => {
      setEditError(null);
      setConnect({ from: variable, x, y });
      setPointer({ x, y });
    },
    [],
  );

  const finishConnect = useCallback(
    (targetVariable: string) => {
      const from = connect?.from;
      setConnect(null);
      setPointer(null);
      setHoverRow(null);
      if (!from || from === targetVariable) return;

      void api
        .addCausalEdge({ source: from, target: targetVariable })
        .then(() => {
          setEditError(null);
          setEdgeRevision((value) => value + 1);
        })
        .catch((cause) => {
          // A refused arrow — a cycle, or one already in the model — has to say
          // why, or the drag just appears to have done nothing.
          setEditError(cause instanceof Error ? cause.message : String(cause));
        });
    },
    [connect],
  );

  /**
   * While a connection is being dragged: track the pointer even once it leaves
   * the canvas, scroll the page when it nears an edge, and cancel on release or
   * Escape.
   *
   * The auto-scroll is what makes the feature usable at all. Editing shows a
   * row for every variable in the graph, which is taller than the window, so
   * without it the rows you most want to reach — the ones off the bottom —
   * simply could not be dropped on.
   */
  useEffect(() => {
    if (!connect) return undefined;
    const EDGE = 90;
    let frame = 0;
    let clientY = 0;

    const step = () => {
      const top = clientY - EDGE;
      const bottom = clientY - (window.innerHeight - EDGE);
      if (top < 0) window.scrollBy(0, Math.max(-24, top / 4));
      else if (bottom > 0) window.scrollBy(0, Math.min(24, bottom / 4));
      frame = window.requestAnimationFrame(step);
    };

    const onMove = (event: MouseEvent) => {
      clientY = event.clientY;
      const point = toSvgPoint(event);
      if (point) setPointer(point);
    };
    const cancel = () => {
      setConnect(null);
      setPointer(null);
      setHoverRow(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') cancel();
    };

    frame = window.requestAnimationFrame(step);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', cancel);
    window.addEventListener('keydown', onKey);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', cancel);
      window.removeEventListener('keydown', onKey);
    };
  }, [connect, toSvgPoint]);

  const removeEdge = useCallback((source: string, target: string) => {
    void api
      .removeCausalEdge(source, target)
      .then(() => {
        setEditError(null);
        setEdgeRevision((value) => value + 1);
      })
      .catch((cause) => {
        setEditError(cause instanceof Error ? cause.message : String(cause));
      });
  }, []);

  /** Drop a caption when an earlier node in the same row is too close. */
  const captionVisible = useMemo(() => {
    const visible = new Set<string>();
    const lastX = new Map<string, number>();
    for (const node of [...geometry.nodes].sort((a, b) => a.x - b.x)) {
      const previous = lastX.get(node.occurrence.variable);
      if (previous === undefined || node.x - previous >= LABEL_GAP) {
        visible.add(node.occurrence.id);
        lastX.set(node.occurrence.variable, node.x);
      }
    }
    return visible;
  }, [geometry]);

  const height = Math.max(ROW_HEIGHT, rows.length * ROW_HEIGHT);
  const kinds = useMemo(() => {
    const seen = new Set(rows.map((row) => row.role));
    return [...seen].sort();
  }, [rows]);

  return (
    <div className="flex flex-col" data-testid="timeline-dag">
      <div className="flex flex-wrap items-center gap-4 border-b border-slate-100 px-5 py-3">
        <VariableSelect
          label="Outcome"
          value={outcome}
          variables={variables}
          onChange={setOutcome}
          testId="dag-outcome"
        />
        <VariableSelect
          label="Exposure"
          value={exposure}
          variables={variables.filter((item) => item.id !== outcome)}
          onChange={setExposure}
          allowNone
          testId="dag-exposure"
        />
        {busy ? <span className="text-[11.5px] text-slate-400">Building…</span> : null}

        <button
          type="button"
          onClick={() => setEditing((value) => !value)}
          aria-expanded={editing}
          data-testid="dag-edit-toggle"
          className={`ml-auto rounded-lg border px-3 py-1.5 text-[12.5px] font-medium transition ${
            editing
              ? 'border-slate-300 bg-slate-100 text-slate-800'
              : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-800'
          }`}
        >
          {editing ? 'Done editing' : 'Edit arrows'}
        </button>
      </div>

      {editing ? (
        <>
          <p className="flex items-center gap-2 border-b border-slate-100 bg-violet-50/50 px-5 py-2 text-[12px] text-violet-900">
            <span
              className="inline-block h-2.5 w-2.5 shrink-0 rounded-full border-2"
              style={{ borderColor: USER_EDGE_COLOR }}
              aria-hidden
            />
            Drag the dot on a node onto another row to draw an arrow. Hover an arrow to
            remove it. Every variable in this graph has a row while editing, even the ones
            today recorded nothing for.
          </p>
          {editError ? (
            <p
              role="alert"
              data-testid="dag-edit-error"
              className="border-b border-rose-100 bg-rose-50 px-5 py-2 text-[12px] leading-relaxed text-rose-800"
            >
              {editError}
            </p>
          ) : null}
        </>
      ) : null}

      {error ? (
        <p role="alert" className="px-5 py-6 text-[12.5px] text-rose-700">
          {error}
        </p>
      ) : null}

      {!error && !placed && !busy ? (
        <p className="px-5 py-10 text-center text-[12.5px] text-slate-500">
          This day has not been processed yet, so there is nothing to place on a clock.
        </p>
      ) : null}

      {placed && scale ? (
        rows.length === 0 ? (
          <p className="px-5 py-10 text-center text-[12.5px] text-slate-500">
            None of the variables in this graph were recorded on this day, so there is nothing to
            place on the clock.
          </p>
        ) : (
          <div className="flex">
            <div
              className="shrink-0 border-r border-slate-100 bg-white"
              style={{ width: LANE_LABEL_WIDTH }}
            >
              <div style={{ height: AXIS_HEIGHT }} />
              {rows.map((row) => (
                <RowLabel key={row.variable} row={row} />
              ))}
              <div style={{ height: AXIS_HEIGHT }} />
            </div>

            <div ref={ref} className="min-w-0 flex-1 overflow-x-auto overflow-y-hidden">
              <div style={{ width: plotWidth }}>
                <AxisRow scale={scale} position="top" />
                <svg
                  ref={svgRef}
                  width={plotWidth}
                  height={height}
                  role="group"
                  aria-label={`Causal graph for ${
                    dag?.outcome ?? 'the outcome'
                  }, placed on the day's clock`}
                  className={`block ${connect ? 'cursor-crosshair' : ''}`}
                >
                  <defs>
                    <marker
                      id="dag-tip-immediate"
                      viewBox="0 0 10 10"
                      refX="9"
                      refY="5"
                      markerWidth="5.5"
                      markerHeight="5.5"
                      orient="auto-start-reverse"
                    >
                      <path d="M 0 0 L 10 5 L 0 10 z" fill={IMMEDIATE_COLOR} />
                    </marker>
                    <marker
                      id="dag-tip-delayed"
                      viewBox="0 0 10 10"
                      refX="9"
                      refY="5"
                      markerWidth="5.5"
                      markerHeight="5.5"
                      orient="auto-start-reverse"
                    >
                      <path d="M 0 0 L 10 5 L 0 10 z" fill={DELAYED_COLOR} />
                    </marker>
                  </defs>

                  {rows.map((row, index) => (
                    <rect
                      key={row.variable}
                      x={0}
                      y={index * ROW_HEIGHT}
                      width={plotWidth}
                      height={ROW_HEIGHT}
                      fill={
                        hoverRow === row.variable && connect && connect.from !== row.variable
                          ? '#eef2ff'
                          : index % 2 === 0
                            ? '#ffffff'
                            : '#fafbfc'
                      }
                    />
                  ))}
                  <GridLines scale={scale} height={height} />
                  {rows.map((row, index) => (
                    <line
                      key={`sep-${row.variable}`}
                      x1={0}
                      x2={plotWidth}
                      y1={(index + 1) * ROW_HEIGHT}
                      y2={(index + 1) * ROW_HEIGHT}
                      stroke="#f1f5f9"
                      strokeWidth={1}
                    />
                  ))}

                  {placed.links.map((link) => (
                    <LinkPath
                      key={`${link.source}->${link.target}`}
                      link={link}
                      from={geometry.byId.get(link.source)}
                      to={geometry.byId.get(link.target)}
                      hovered={
                        hovered?.source === link.source && hovered?.target === link.target
                      }
                      onHover={setHovered}
                      timeZone={placed.localTimezone}
                      editing={editing}
                      onRemove={removeEdge}
                    />
                  ))}

                  {geometry.nodes.map((node) => (
                    <Node
                      key={node.occurrence.id}
                      node={node}
                      timeZone={placed.localTimezone}
                      selected={selected?.id === node.occurrence.id}
                      showCaption={captionVisible.has(node.occurrence.id)}
                      plotWidth={plotWidth}
                      editing={editing}
                      connecting={connect?.from === node.occurrence.variable}
                      onStartConnect={startConnect}
                      onSelect={(occurrence) =>
                        setSelected((current) =>
                          current?.id === occurrence.id ? null : occurrence,
                        )
                      }
                    />
                  ))}

                  {/* Variables the day recorded nothing for still need somewhere
                      to grab, or the arrows most worth adding — to stress, to
                      work schedule — could never be drawn. */}
                  {editing
                    ? rows.map((row, index) =>
                        geometry.nodes.some((node) => node.occurrence.variable === row.variable)
                          ? null
                          : (
                              <Anchor
                                key={`anchor-${row.variable}`}
                                row={row}
                                x={PAD_LEFT + 22}
                                y={index * ROW_HEIGHT + ROW_HEIGHT / 2}
                                connecting={connect?.from === row.variable}
                                onStartConnect={startConnect}
                              />
                            ),
                      )
                    : null}

                  {/* Whole rows are the drop target: aiming at a node would
                      make connecting fiddly, and every node in a row stands for
                      the same variable anyway. Live only mid-drag so it never
                      swallows a click. */}
                  {connect
                    ? rows.map((row, index) => (
                        <rect
                          key={`drop-${row.variable}`}
                          x={0}
                          y={index * ROW_HEIGHT}
                          width={plotWidth}
                          height={ROW_HEIGHT}
                          fill="transparent"
                          data-testid={`dag-drop-${row.variable}`}
                          onMouseEnter={() => setHoverRow(row.variable)}
                          onMouseUp={() => finishConnect(row.variable)}
                        />
                      ))
                    : null}

                  {connect && pointer ? (
                    <g pointerEvents="none">
                      <path
                        d={`M${connect.x} ${connect.y} C${connect.x + 40} ${connect.y}, ${
                          pointer.x - 40
                        } ${pointer.y}, ${pointer.x} ${pointer.y}`}
                        fill="none"
                        stroke={USER_EDGE_COLOR}
                        strokeWidth={2}
                        strokeDasharray="5 4"
                      />
                      <circle cx={pointer.x} cy={pointer.y} r={4} fill={USER_EDGE_COLOR} />
                    </g>
                  ) : null}
                </svg>
                <AxisRow scale={scale} position="bottom" />
              </div>
            </div>
          </div>
        )
      ) : null}

      {hovered ? (
        <p
          className="border-t border-slate-100 bg-slate-50/70 px-5 py-2 text-[12px] leading-relaxed text-slate-600"
          data-testid="dag-link-caption"
        >
          <span
            className="font-semibold"
            style={{ color: hovered.kind === 'delayed' ? DELAYED_COLOR : IMMEDIATE_COLOR }}
          >
            {hovered.kind === 'delayed' ? 'Delayed effect' : 'Immediate effect'}
          </span>{' '}
          · {formatLag(hovered.lagMinutes)} · {strengthStyle(hovered.strength).label} —{' '}
          {hovered.rationale}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-slate-100 px-5 py-2.5 text-[10.5px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <svg width="26" height="8" aria-hidden>
            <line x1="0" y1="4" x2="26" y2="4" stroke={IMMEDIATE_COLOR} strokeWidth="1.9" />
          </svg>
          Immediate — within 2 hours
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="26" height="8" aria-hidden>
            <line
              x1="0"
              y1="4"
              x2="26"
              y2="4"
              stroke={DELAYED_COLOR}
              strokeWidth="1.9"
              strokeDasharray="5 4"
            />
          </svg>
          Delayed — hours later
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="26" height="8" aria-hidden>
            <line
              x1="0"
              y1="4"
              x2="26"
              y2="4"
              stroke={IMMEDIATE_COLOR}
              strokeWidth="1.2"
              opacity="0.55"
            />
          </svg>
          Fainter — weaker evidence for the link
        </span>
        {placed?.links.some((link) => link.origin === 'user') ? (
          <span className="flex items-center gap-1.5">
            <svg width="12" height="12" aria-hidden>
              <circle
                cx="6"
                cy="6"
                r="3.6"
                fill="#ffffff"
                stroke={USER_EDGE_COLOR}
                strokeWidth="2"
              />
            </svg>
            An arrow you added
          </span>
        ) : null}
        {kinds.map((role) => (
          <span key={role} className="flex items-center gap-1.5">
            <span
              className="h-3 w-3 rounded-full border-[1.5px]"
              style={{
                backgroundColor: OUTLINED_ROLES.has(role) ? '#ffffff' : roleStyle(role).solid,
                borderColor: roleStyle(role).solid,
              }}
              aria-hidden
            />
            {roleStyle(role).label}
          </span>
        ))}
      </div>

      {selected ? (
        <div className="border-t border-slate-100 px-5 py-3" data-testid="dag-node-detail">
          <h3 className="text-[12.5px] font-semibold text-slate-800">
            {selected.label}
            <span className="ml-2 font-normal text-slate-500">
              {placed
                ? formatTime(selected.start, placed.localTimezone) +
                  (selected.end && selected.end !== selected.start
                    ? ` – ${formatTime(selected.end, placed.localTimezone)}`
                    : '')
                : null}
            </span>
          </h3>
          {selected.detail ? (
            <p className="mt-1 text-[12px] text-slate-600">{selected.detail}</p>
          ) : null}
          <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
            {selected.kind === 'constant'
              ? 'Known from the calendar, true for every hour of the day.'
              : selected.kind === 'span'
                ? 'Recorded as a state that held all day.'
                : selected.kind === 'reading'
                  ? 'A single value the source published for this day.'
                  : 'Open the Expanded tab and click this event to see its raw records.'}
          </p>
        </div>
      ) : null}

      {editing ? (
        <EdgeEditor
          onChanged={() => setEdgeRevision((value) => value + 1)}
        />
      ) : null}
    </div>
  );
}

interface PlacedNode {
  occurrence: DagOccurrence;
  x: number;
  xEnd: number;
  y: number;
  role: string;
}

/**
 * The grab point for drawing an arrow, in the style of a diagram editor: a
 * small dot on the node's trailing edge. A dedicated handle rather than the
 * whole node, so clicking a node still opens its detail instead of starting a
 * drag every time.
 */
function ConnectHandle({
  x,
  y,
  active,
  onStart,
  testId,
}: {
  x: number;
  y: number;
  active: boolean;
  onStart: (x: number, y: number) => void;
  testId: string;
}) {
  return (
    <circle
      cx={x}
      cy={y}
      r={5.5}
      fill={active ? USER_EDGE_COLOR : '#ffffff'}
      stroke={USER_EDGE_COLOR}
      strokeWidth={2}
      className="cursor-crosshair"
      data-testid={testId}
      onMouseDown={(event) => {
        event.stopPropagation();
        event.preventDefault();
        onStart(x, y);
      }}
    >
      <title>Drag to another row to draw an arrow</title>
    </circle>
  );
}

function Node({
  node,
  timeZone,
  selected,
  showCaption,
  plotWidth,
  editing,
  connecting,
  onStartConnect,
  onSelect,
}: {
  node: PlacedNode;
  timeZone: string;
  selected: boolean;
  showCaption: boolean;
  plotWidth: number;
  editing: boolean;
  connecting: boolean;
  onStartConnect: (variable: string, x: number, y: number) => void;
  onSelect: (occurrence: DagOccurrence) => void;
}) {
  const { occurrence, x, xEnd, y } = node;
  const style = roleStyle(node.role);
  const outlined = OUTLINED_ROLES.has(node.role);
  const isBand = occurrence.kind === 'span' || occurrence.kind === 'constant';
  const activate = () => onSelect(occurrence);
  // A node at midnight would have half its caption cut off by the plot edge.
  const anchor: 'start' | 'middle' | 'end' =
    x < 70 ? 'start' : x > plotWidth - 70 ? 'end' : 'middle';
  const captionX = anchor === 'start' ? x - NODE_RADIUS : anchor === 'end' ? x + NODE_RADIUS : x;

  if (isBand) {
    // A state that held all day is true at every hour, so it gets the whole
    // width rather than a node pretending it happened at one moment.
    return (
      <g
        role="button"
        tabIndex={0}
        className="tl-mark"
        data-testid={`dag-node-${occurrence.variable}`}
        aria-label={`${occurrence.label}, held all day`}
        onClick={activate}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            activate();
          }
        }}
      >
        <title>{`${occurrence.label} — ${occurrence.detail || 'held all day'}`}</title>
        <rect
          x={x}
          y={y - (NODE_RADIUS - 1)}
          width={Math.max(4, xEnd - x)}
          height={(NODE_RADIUS - 1) * 2}
          rx={9}
          fill={style.fill}
          stroke={style.stroke}
          strokeWidth={selected ? 2 : 1.1}
          opacity={0.9}
        />
        <g
          transform={`translate(${x + 9}, ${y - ICON_SIZE / 2})`}
          style={{ color: style.text }}
          pointerEvents="none"
        >
          <VariableIcon variable={occurrence.variable} size={ICON_SIZE} strokeWidth={1.7} />
        </g>
        <text
          x={x + Math.max(4, xEnd - x) / 2}
          y={y + 4}
          textAnchor="middle"
          fontSize={11}
          fontWeight={600}
          fill={style.text}
          pointerEvents="none"
        >
          {occurrence.label}
        </text>
      </g>
    );
  }

  const hasDuration = xEnd - x > 3;
  return (
    <g
      role="button"
      tabIndex={0}
      className="tl-mark"
      data-testid={`dag-node-${occurrence.variable}`}
      aria-label={`${occurrence.label} at ${formatTime(occurrence.start, timeZone)}${
        occurrence.detail ? `, ${occurrence.detail}` : ''
      }`}
      onClick={activate}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          activate();
        }
      }}
    >
      <title>{`${occurrence.label} — ${occurrence.detail}`}</title>

      {hasDuration ? (
        <rect
          x={x}
          y={y - BAR_HEIGHT / 2}
          width={xEnd - x}
          height={BAR_HEIGHT}
          rx={BAR_HEIGHT / 2}
          fill={style.solid}
          opacity={0.26}
        />
      ) : null}

      {showCaption ? (
        <text
          x={captionX}
          y={y - NODE_RADIUS - 8}
          textAnchor={anchor}
          fontSize={10.5}
          fontWeight={600}
          fill={style.stroke}
          pointerEvents="none"
        >
          {compactTime(occurrence.start, timeZone)}
        </text>
      ) : null}

      {/* A white ring lifts the node off the duration bar running under it. */}
      <circle cx={x} cy={y} r={NODE_RADIUS + 2} fill="#ffffff" />
      <circle
        cx={x}
        cy={y}
        r={NODE_RADIUS}
        fill={outlined ? '#ffffff' : style.solid}
        stroke={style.solid}
        strokeWidth={selected ? 2.8 : outlined ? 1.8 : 1}
      />
      {/* The glyph says which variable this is; the row label alone makes the
          reader look away from the node to find out. */}
      <g
        transform={`translate(${x - ICON_SIZE / 2}, ${y - ICON_SIZE / 2})`}
        style={{ color: outlined ? style.solid : '#ffffff' }}
        pointerEvents="none"
      >
        <VariableIcon variable={occurrence.variable} size={ICON_SIZE} strokeWidth={1.9} />
      </g>

      {showCaption && occurrence.detail ? (
        <text
          x={captionX}
          y={y + NODE_RADIUS + 14}
          textAnchor={anchor}
          fontSize={10}
          fill="#64748b"
          pointerEvents="none"
        >
          {occurrence.detail.length > 24
            ? `${occurrence.detail.slice(0, 23)}…`
            : occurrence.detail}
        </text>
      ) : null}

      {/* A generous invisible target: the visible circle alone is a small hit area. */}
      <rect
        x={x - NODE_RADIUS - 4}
        y={y - NODE_RADIUS - 4}
        width={Math.max(xEnd - x, 0) + (NODE_RADIUS + 4) * 2}
        height={(NODE_RADIUS + 4) * 2}
        fill="transparent"
      />

      {editing ? (
        <ConnectHandle
          x={Math.max(x, xEnd) + NODE_RADIUS + 3}
          y={y}
          active={connecting}
          testId={`dag-handle-${occurrence.variable}`}
          onStart={(hx, hy) => onStartConnect(occurrence.variable, hx, hy)}
        />
      ) : null}
    </g>
  );
}

/**
 * A stand-in node for a variable the day recorded nothing for. Only drawn while
 * editing: in view mode an empty row would assert a presence the data does not
 * support, but while wiring the model you have to be able to reach it.
 */
function Anchor({
  row,
  x,
  y,
  connecting,
  onStartConnect,
}: {
  row: DagRow;
  x: number;
  y: number;
  connecting: boolean;
  onStartConnect: (variable: string, x: number, y: number) => void;
}) {
  const style = roleStyle(row.role);
  return (
    <g data-testid={`dag-anchor-${row.variable}`}>
      <title>{`${row.label} — ${row.note}`}</title>
      <circle
        cx={x}
        cy={y}
        r={NODE_RADIUS}
        fill="#ffffff"
        stroke={style.solid}
        strokeWidth={1.4}
        strokeDasharray="4 3"
        opacity={0.85}
      />
      <g
        transform={`translate(${x - ICON_SIZE / 2}, ${y - ICON_SIZE / 2})`}
        style={{ color: style.solid }}
        opacity={0.6}
        pointerEvents="none"
      >
        <VariableIcon variable={row.variable} size={ICON_SIZE} strokeWidth={1.7} />
      </g>
      <text
        x={x}
        y={y + NODE_RADIUS + 14}
        textAnchor="middle"
        fontSize={9.5}
        fill="#94a3b8"
        pointerEvents="none"
      >
        no data this day
      </text>
      <ConnectHandle
        x={x + NODE_RADIUS + 3}
        y={y}
        active={connecting}
        testId={`dag-handle-${row.variable}`}
        onStart={(hx, hy) => onStartConnect(row.variable, hx, hy)}
      />
    </g>
  );
}

function LinkPath({
  link,
  from,
  to,
  hovered,
  onHover,
  timeZone,
  editing,
  onRemove,
}: {
  link: DagLink;
  from: PlacedNode | undefined;
  to: PlacedNode | undefined;
  hovered: boolean;
  onHover: (link: DagLink | null) => void;
  timeZone: string;
  editing: boolean;
  onRemove: (source: string, target: string) => void;
}) {
  if (!from || !to) return null;

  const delayed = link.kind === 'delayed';
  const color = delayed ? DELAYED_COLOR : IMMEDIATE_COLOR;
  const strength = strengthStyle(link.strength);

  const y1 = from.y;
  const y2 = to.y;
  const causeEnds = Math.max(from.x, from.xEnd);
  const arrives = to.x - NODE_RADIUS - 3;

  // Where the arrow leaves depends on whether the effect waited for the cause
  // to finish. An effect that begins *during* a long cause must not be drawn
  // leaving from the cause's end, or the arrow would point backwards in time.
  let d: string;
  // Roughly where the curve passes through, for the "you drew this" marker.
  let midX: number;
  let midY: number;
  if (arrives > causeEnds + NODE_RADIUS) {
    const x1 = causeEnds + (from.xEnd > from.x ? 2 : NODE_RADIUS);
    const dx = Math.max(18, (arrives - x1) * 0.4);
    // Delayed links bow away from the straight line so a long reach across the
    // day stays readable instead of cutting through every row between.
    const bow = delayed ? Math.min(34, 12 + (arrives - x1) * 0.05) : 0;
    d = delayed
      ? `M${x1} ${y1} C${x1 + dx} ${y1 - bow}, ${arrives - dx} ${y2 - bow}, ${arrives} ${y2}`
      : `M${x1} ${y1} C${x1 + dx} ${y1}, ${arrives - dx} ${y2}, ${arrives} ${y2}`;
    midX = (x1 + arrives) / 2;
    midY = (y1 + y2) / 2 - bow * 0.75;
  } else if (arrives > from.x + NODE_RADIUS) {
    const x1 = from.x + NODE_RADIUS + 2;
    const dx = Math.max(12, (arrives - x1) * 0.4);
    d = `M${x1} ${y1} C${x1 + dx} ${y1}, ${arrives - dx} ${y2}, ${arrives} ${y2}`;
    midX = (x1 + arrives) / 2;
    midY = (y1 + y2) / 2;
  } else {
    // Cause and effect are recorded at effectively the same moment, so the link
    // is a short hop between rows rather than a reach across the day.
    const direction = y2 > y1 ? 1 : -1;
    const startY = y1 + direction * NODE_RADIUS;
    const endY = y2 - direction * (NODE_RADIUS + 3);
    d =
      `M${from.x} ${startY} C${from.x + 16} ${startY + direction * 12}, ` +
      `${to.x + 16} ${endY - direction * 12}, ${to.x} ${endY}`;
    midX = (from.x + to.x) / 2 + 8;
    midY = (startY + endY) / 2;
  }

  return (
    <g
      onMouseEnter={() => onHover(link)}
      onMouseLeave={() => onHover(null)}
      className="cursor-help"
    >
      <title>
        {`${link.rationale} (${strength.label}, ${formatLag(link.lagMinutes)}, effect at ${formatTime(
          to.occurrence.start,
          timeZone,
        )})`}
      </title>
      {link.onPath ? (
        // The exposure → outcome path, haloed rather than recoloured so the
        // timing and strength encodings stay readable.
        <path d={d} fill="none" stroke={color} strokeWidth={7} opacity={0.13} />
      ) : null}
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={hovered ? strength.width + 1 : strength.width}
        strokeDasharray={delayed ? '6 5' : undefined}
        opacity={hovered ? 1 : strength.opacity}
        markerEnd={`url(#dag-tip-${delayed ? 'delayed' : 'immediate'})`}
      />
      {link.origin === 'user' ? (
        // Colour and dash already carry timing, and width carries evidence, so
        // "you drew this" gets a mark of its own rather than a fourth
        // reinterpretation of the line itself.
        <circle
          cx={midX}
          cy={midY}
          r={3.6}
          fill="#ffffff"
          stroke={USER_EDGE_COLOR}
          strokeWidth={2}
        />
      ) : null}
      <path d={d} fill="none" stroke="transparent" strokeWidth={12} />

      {/* While editing, an arrow carries its own delete control at the midpoint
          — the same place the eye already goes when hovering it. */}
      {editing && hovered ? (
        <g
          className="cursor-pointer"
          data-testid={`dag-link-remove-${link.sourceVariable}-${link.targetVariable}`}
          onClick={(event) => {
            event.stopPropagation();
            onRemove(link.sourceVariable, link.targetVariable);
          }}
        >
          <title>{`Remove ${link.sourceVariable} → ${link.targetVariable}`}</title>
          <circle cx={midX} cy={midY} r={9} fill="#ffffff" stroke="#e11d48" strokeWidth={1.6} />
          <path
            d={`M${midX - 3.5} ${midY - 3.5}L${midX + 3.5} ${midY + 3.5}M${midX + 3.5} ${
              midY - 3.5
            }L${midX - 3.5} ${midY + 3.5}`}
            stroke="#e11d48"
            strokeWidth={1.8}
            strokeLinecap="round"
          />
        </g>
      ) : null}
    </g>
  );
}
