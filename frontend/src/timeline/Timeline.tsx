/**
 * The expanded swimlane view.
 *
 * A fixed label column sits beside one horizontally scrollable plot column, so
 * every lane shares the same x-scale and the alignment between lanes is exact.
 */

import { useMemo } from 'react';
import { LaneLabel, LanePlot } from '../lanes/LaneRow';
import type { DayTimeline, Lane, Selection } from '../types/timeline';
import { useElementWidth } from '../hooks/useElementWidth';
import { AXIS_HEIGHT, LANE_LABEL_WIDTH, laneHeight } from '../utilities/lanes';
import { AxisRow, GridLines } from './Axis';
import { createScale } from './scale';

const MIN_PLOT_WIDTH = 560;

interface TimelineProps {
  timeline: DayTimeline;
  lanes: Lane[];
  selectedKey: string | null;
  onSelect: (selection: Selection) => void;
  zoom: number;
}

export function Timeline({ timeline, lanes, selectedKey, onSelect, zoom }: TimelineProps) {
  const { ref, width } = useElementWidth<HTMLDivElement>(900);
  const plotWidth = Math.max(width, MIN_PLOT_WIDTH) * zoom;

  const scale = useMemo(
    () => createScale(timeline.dayStart, timeline.dayEnd, plotWidth, timeline.localTimezone),
    [timeline.dayStart, timeline.dayEnd, timeline.localTimezone, plotWidth],
  );

  const gridByHeight = useMemo(() => {
    const cache = new Map<number, JSX.Element>();
    for (const lane of lanes) {
      const height = laneHeight(lane.id);
      if (!cache.has(height)) cache.set(height, <GridLines scale={scale} height={height} />);
    }
    return cache;
  }, [lanes, scale]);

  return (
    <div className="flex" data-testid="timeline-expanded">
      <div
        className="shrink-0 border-r border-slate-100 bg-white"
        style={{ width: LANE_LABEL_WIDTH }}
      >
        <div style={{ height: AXIS_HEIGHT }} />
        {lanes.map((lane) => (
          <LaneLabel key={lane.id} lane={lane} />
        ))}
        <div style={{ height: AXIS_HEIGHT }} />
      </div>

      <div ref={ref} className="min-w-0 flex-1 overflow-x-auto overflow-y-hidden">
        <div style={{ width: plotWidth }}>
          <AxisRow scale={scale} position="top" />
          {lanes.map((lane) => (
            <LanePlot
              key={lane.id}
              lane={lane}
              scale={scale}
              timeZone={timeline.localTimezone}
              selectedKey={selectedKey}
              onSelect={onSelect}
              gridLines={gridByHeight.get(laneHeight(lane.id)) ?? <GridLines scale={scale} height={laneHeight(lane.id)} />}
            />
          ))}
          <AxisRow scale={scale} position="bottom" />
        </div>
      </div>
    </div>
  );
}
