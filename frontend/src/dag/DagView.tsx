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

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  api,
  type DagLink,
  type DagOccurrence,
  type DagResponse,
  type DagRow,
  type DagVariable,
} from '../api/client';
import { useElementWidth } from '../hooks/useElementWidth';
import { InfoIcon, VariableIcon } from '../components/Icons';
import { AxisRow, GridLines } from '../timeline/Axis';
import { createScale } from '../timeline/scale';
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
  }, [date, outcome, exposure]);

  const placed = dag?.timeline ?? null;
  const plotWidth = Math.max(width, MIN_PLOT_WIDTH);

  const scale = useMemo(
    () =>
      placed
        ? createScale(placed.dayStart, placed.dayEnd, plotWidth, placed.localTimezone)
        : null,
    [placed, plotWidth],
  );

  /** Rows the day can actually draw, kept in the backend's cause-first order. */
  const rows = useMemo(() => {
    if (!placed) return [];
    const withData = new Set(placed.occurrences.map((item) => item.variable));
    return placed.rows.filter((row) => withData.has(row.variable));
  }, [placed]);

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
      </div>

      <p className="flex items-start gap-2 border-b border-slate-100 bg-amber-50/40 px-5 py-2.5 text-[12px] leading-relaxed text-amber-900">
        <InfoIcon size={15} className="mt-0.5 shrink-0" />
        <span>
          <strong className="font-semibold">These arrows are assumptions, not findings.</strong>{' '}
          The nodes are real — each sits at the hour your data recorded it. The arrows between
          them come from published physiology and have not been estimated or tested against your
          day.
        </span>
      </p>

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
                  width={plotWidth}
                  height={height}
                  role="group"
                  aria-label={`Causal graph for ${
                    dag?.outcome ?? 'the outcome'
                  }, placed on the day's clock`}
                  className="block"
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
                      fill={index % 2 === 0 ? '#ffffff' : '#fafbfc'}
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
                      onSelect={(occurrence) =>
                        setSelected((current) =>
                          current?.id === occurrence.id ? null : occurrence,
                        )
                      }
                    />
                  ))}
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

function Node({
  node,
  timeZone,
  selected,
  showCaption,
  plotWidth,
  onSelect,
}: {
  node: PlacedNode;
  timeZone: string;
  selected: boolean;
  showCaption: boolean;
  plotWidth: number;
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
}: {
  link: DagLink;
  from: PlacedNode | undefined;
  to: PlacedNode | undefined;
  hovered: boolean;
  onHover: (link: DagLink | null) => void;
  timeZone: string;
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
  if (arrives > causeEnds + NODE_RADIUS) {
    const x1 = causeEnds + (from.xEnd > from.x ? 2 : NODE_RADIUS);
    const dx = Math.max(18, (arrives - x1) * 0.4);
    // Delayed links bow away from the straight line so a long reach across the
    // day stays readable instead of cutting through every row between.
    const bow = delayed ? Math.min(34, 12 + (arrives - x1) * 0.05) : 0;
    d = delayed
      ? `M${x1} ${y1} C${x1 + dx} ${y1 - bow}, ${arrives - dx} ${y2 - bow}, ${arrives} ${y2}`
      : `M${x1} ${y1} C${x1 + dx} ${y1}, ${arrives - dx} ${y2}, ${arrives} ${y2}`;
  } else if (arrives > from.x + NODE_RADIUS) {
    const x1 = from.x + NODE_RADIUS + 2;
    const dx = Math.max(12, (arrives - x1) * 0.4);
    d = `M${x1} ${y1} C${x1 + dx} ${y1}, ${arrives - dx} ${y2}, ${arrives} ${y2}`;
  } else {
    // Cause and effect are recorded at effectively the same moment, so the link
    // is a short hop between rows rather than a reach across the day.
    const direction = y2 > y1 ? 1 : -1;
    const startY = y1 + direction * NODE_RADIUS;
    const endY = y2 - direction * (NODE_RADIUS + 3);
    d =
      `M${from.x} ${startY} C${from.x + 16} ${startY + direction * 12}, ` +
      `${to.x + 16} ${endY - direction * 12}, ${to.x} ${endY}`;
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
      <path d={d} fill="none" stroke="transparent" strokeWidth={12} />
    </g>
  );
}
