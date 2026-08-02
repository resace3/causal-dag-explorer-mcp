import { ChevronDownIcon, ChevronUpIcon, CloseIcon, GripIcon, LaneIcon } from '../components/Icons';
import type { DayScale } from '../timeline/scale';
import type { Lane, Selection } from '../types/timeline';
import { accentTheme, laneHeight } from '../utilities/lanes';
import { ActivityLane } from './ActivityLane';
import { ComputerUseLane } from './ComputerUseLane';
import { ContinuousLane } from './ContinuousLane';
import { EnvironmentLane } from './EnvironmentLane';
import { EventLane } from './EventLane';
import { LocationLane } from './LocationLane';
import { PhoneUseLane } from './PhoneUseLane';
import { PresenceLane } from './PresenceLane';
import { laneAriaLabel, type LaneRenderProps } from './shared';

/** Each lane picks the clearest encoding for its data; the x-axis is shared. */
function renderer(lane: Lane): (props: LaneRenderProps) => JSX.Element {
  if (lane.id === 'environment') return EnvironmentLane;
  if (lane.id === 'presence') return PresenceLane;
  if (lane.id === 'location') return LocationLane;
  // Three tiers that read as one column: at the machine, in what, on which site.
  if (lane.id === 'computer_use') return ComputerUseLane;
  // The same idea with two tiers: screen on, and which app was in front.
  if (lane.id === 'phone_use') return PhoneUseLane;
  // And again for the third screen: set on, and what was playing.
  if (lane.id === 'tv') return TvLane;
  // Activity keeps named sessions in front of a step-rate context line.
  if (lane.id === 'activity') return ActivityLane;
  if (lane.series.length > 0) return ContinuousLane;
  return EventLane;
}

export interface LaneReorder {
  onMoveUp: () => void;
  onMoveDown: () => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
  onDragStart: () => void;
  onDragOver: () => void;
  onDrop: () => void;
  onDragEnd: () => void;
  dragging: boolean;
  /** True while a dragged row is hovering over this one. */
  dropTarget: boolean;
}

export function LaneLabel({
  lane,
  reorder,
  onHide,
  onDelete,
}: {
  lane: Lane;
  reorder?: LaneReorder;
  onHide?: () => void;
  /** Present only for rows the user added, where removal is permanent. */
  onDelete?: () => void;
}) {
  const theme = accentTheme(lane.accent);

  return (
    <div
      className={`group relative flex items-center gap-2 border-b border-slate-100 pl-2 pr-5 transition ${
        reorder?.dragging ? 'opacity-40' : ''
      } ${reorder?.dropTarget ? 'bg-slate-50' : ''}`}
      style={{ height: laneHeight(lane.id) }}
      data-testid={`lane-label-${lane.id}`}
      draggable={reorder ? true : undefined}
      onDragStart={reorder?.onDragStart}
      onDragOver={
        reorder
          ? (event) => {
              event.preventDefault(); // without this the drop never fires
              reorder.onDragOver();
            }
          : undefined
      }
      onDrop={
        reorder
          ? (event) => {
              event.preventDefault();
              reorder.onDrop();
            }
          : undefined
      }
      onDragEnd={reorder?.onDragEnd}
    >
      {/* A line across the top marks where the dragged row would land. */}
      {reorder?.dropTarget ? (
        <span
          className="pointer-events-none absolute inset-x-2 top-0 h-0.5 rounded bg-slate-400"
          aria-hidden
        />
      ) : null}

      {reorder ? (
        <span
          className="flex w-5 shrink-0 cursor-grab flex-col items-center text-slate-300 opacity-0 transition group-hover:opacity-100 active:cursor-grabbing"
          data-testid={`lane-grip-${lane.id}`}
        >
          <button
            type="button"
            onClick={reorder.onMoveUp}
            disabled={!reorder.canMoveUp}
            aria-label={`Move ${lane.label} up`}
            data-testid={`lane-move-up-${lane.id}`}
            className="rounded text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-0"
          >
            <ChevronUpIcon size={13} />
          </button>
          <GripIcon size={14} />
          <button
            type="button"
            onClick={reorder.onMoveDown}
            disabled={!reorder.canMoveDown}
            aria-label={`Move ${lane.label} down`}
            data-testid={`lane-move-down-${lane.id}`}
            className="rounded text-slate-400 transition hover:bg-slate-100 hover:text-slate-700 disabled:opacity-0"
          >
            <ChevronDownIcon size={13} />
          </button>
        </span>
      ) : null}

      <span
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border"
        style={{ borderColor: theme.soft, backgroundColor: `${theme.band}`, color: theme.stroke }}
      >
        <LaneIcon laneId={lane.id} size={19} />
      </span>
      <span className="min-w-0 flex-1">
        <span
          className="block truncate text-[13.5px] font-semibold leading-tight"
          style={{ color: theme.text }}
        >
          {lane.label}
        </span>
        <span className="mt-0.5 block truncate text-[11.5px] leading-tight text-slate-500">
          {lane.description}
        </span>
      </span>

      {onDelete || onHide ? (
        <button
          type="button"
          onClick={onDelete ?? onHide}
          // Inside a draggable row, so it must not become a drag source itself.
          draggable={false}
          aria-label={onDelete ? `Delete ${lane.label}` : `Hide ${lane.label}`}
          // A bare × invites the reading that the data itself is being removed,
          // so the title says which of the two this is. A built-in row is only
          // hidden; a row the user added is genuinely gone.
          title={
            onDelete
              ? `Delete “${lane.label}” — you added this row, so removing it is permanent`
              : `Hide ${lane.label} — restore it from “Visible data streams”`
          }
          data-testid={onDelete ? `lane-delete-${lane.id}` : `lane-hide-${lane.id}`}
          // Floated rather than laid out: at opacity-0 it would still occupy
          // its width, permanently narrowing the lane description for the sake
          // of a control that is invisible most of the time. The white backing
          // keeps it legible over any text it happens to cover on hover.
          className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md bg-white p-1 text-slate-300 opacity-0 shadow-sm transition hover:bg-rose-50 hover:text-rose-500 focus-visible:opacity-100 group-hover:opacity-100"
        >
          <CloseIcon size={14} />
        </button>
      ) : null}
    </div>
  );
}

interface LanePlotProps {
  lane: Lane;
  scale: DayScale;
  timeZone: string;
  selectedKey: string | null;
  onSelect: (selection: Selection) => void;
  gridLines: JSX.Element;
}

export function LanePlot({
  lane,
  scale,
  timeZone,
  selectedKey,
  onSelect,
  gridLines,
}: LanePlotProps) {
  const height = laneHeight(lane.id);
  const theme = accentTheme(lane.accent);
  const Renderer = renderer(lane);

  return (
    <div
      className="border-b border-slate-100"
      style={{ height, backgroundColor: theme.band }}
      data-testid={`lane-plot-${lane.id}`}
    >
      <svg
        width={scale.width}
        height={height}
        role="group"
        aria-label={laneAriaLabel(lane)}
        className="block"
      >
        {gridLines}
        <Renderer
          lane={lane}
          scale={scale}
          height={height}
          timeZone={timeZone}
          selectedKey={selectedKey}
          onSelect={onSelect}
        />
      </svg>
    </div>
  );
}
