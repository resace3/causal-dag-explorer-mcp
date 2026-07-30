import { LaneIcon } from '../components/Icons';
import type { DayScale } from '../timeline/scale';
import type { Lane, Selection } from '../types/timeline';
import { accentTheme, laneHeight } from '../utilities/lanes';
import { ActivityLane } from './ActivityLane';
import { ContinuousLane } from './ContinuousLane';
import { EnvironmentLane } from './EnvironmentLane';
import { EventLane } from './EventLane';
import { LocationLane } from './LocationLane';
import { PresenceLane } from './PresenceLane';
import { laneAriaLabel, type LaneRenderProps } from './shared';

/** Each lane picks the clearest encoding for its data; the x-axis is shared. */
function renderer(lane: Lane): (props: LaneRenderProps) => JSX.Element {
  if (lane.id === 'environment') return EnvironmentLane;
  if (lane.id === 'presence') return PresenceLane;
  if (lane.id === 'location') return LocationLane;
  // Activity keeps named sessions in front of a step-rate context line.
  if (lane.id === 'activity') return ActivityLane;
  if (lane.series.length > 0) return ContinuousLane;
  return EventLane;
}

export function LaneLabel({ lane }: { lane: Lane }) {
  const theme = accentTheme(lane.accent);
  return (
    <div
      className="flex items-center gap-3 border-b border-slate-100 px-5"
      style={{ height: laneHeight(lane.id) }}
      data-testid={`lane-label-${lane.id}`}
    >
      <span
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border"
        style={{ borderColor: theme.soft, backgroundColor: `${theme.band}`, color: theme.stroke }}
      >
        <LaneIcon laneId={lane.id} size={19} />
      </span>
      <span className="min-w-0">
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
