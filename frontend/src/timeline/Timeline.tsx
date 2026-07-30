/**
 * The expanded swimlane view.
 *
 * A fixed label column sits beside one horizontally scrollable plot column, so
 * every lane shares the same x-scale and the alignment between lanes is exact.
 */

import { useMemo, useState } from 'react';
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
  /** Move `laneId` so it sits where `beforeLaneId` currently is. */
  onReorder?: (laneId: string, beforeLaneId: string) => void;
}

export function Timeline({
  timeline,
  lanes,
  selectedKey,
  onSelect,
  zoom,
  onReorder,
}: TimelineProps) {
  const { ref, width } = useElementWidth<HTMLDivElement>(900);
  const plotWidth = Math.max(width, MIN_PLOT_WIDTH) * zoom;
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);

  const move = (laneId: string, direction: -1 | 1) => {
    const index = lanes.findIndex((lane) => lane.id === laneId);
    const neighbour = lanes[index + direction];
    if (!onReorder || !neighbour) return;
    onReorder(laneId, neighbour.id);
  };

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
        {lanes.map((lane, index) => (
          <LaneLabel
            key={lane.id}
            lane={lane}
            reorder={
              onReorder
                ? {
                    onMoveUp: () => move(lane.id, -1),
                    onMoveDown: () => move(lane.id, 1),
                    canMoveUp: index > 0,
                    canMoveDown: index < lanes.length - 1,
                    onDragStart: () => setDragging(lane.id),
                    onDragOver: () => setOver(lane.id),
                    onDrop: () => {
                      if (dragging && dragging !== lane.id) onReorder(dragging, lane.id);
                      setDragging(null);
                      setOver(null);
                    },
                    onDragEnd: () => {
                      setDragging(null);
                      setOver(null);
                    },
                    dragging: dragging === lane.id,
                    dropTarget: over === lane.id && dragging !== null && dragging !== lane.id,
                  }
                : undefined
            }
          />
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
