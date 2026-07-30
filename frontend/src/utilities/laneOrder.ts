/**
 * Applying the user's row order to whatever lanes a given day actually has.
 *
 * The saved order is a list of lane ids and is routinely stale in both
 * directions: a lane disappears on a day with no data for it, and a new lane
 * appears when a source starts reporting. Neither may lose the arrangement —
 * a lane that vanishes today and returns tomorrow has to come back where the
 * user left it.
 */

export interface Orderable {
  id: string;
}

/** Sort `lanes` by `order`, sending anything unrecognised to the bottom. */
export function applyLaneOrder<T extends Orderable>(lanes: T[], order: string[]): T[] {
  const rank = new Map(order.map((id, index) => [id, index]));
  return [...lanes].sort((a, b) => {
    const left = rank.get(a.id) ?? Number.MAX_SAFE_INTEGER;
    const right = rank.get(b.id) ?? Number.MAX_SAFE_INTEGER;
    // Equal rank means both are new: keep the order the payload gave them.
    if (left !== right) return left - right;
    return lanes.indexOf(a) - lanes.indexOf(b);
  });
}

/**
 * Move `laneId` to where `beforeLaneId` currently sits, returning the full
 * saved order — including ids for lanes not on screen today, which are kept so
 * a day with fewer lanes cannot silently erase the rest of the arrangement.
 */
export function moveLaneBefore(
  visibleIds: string[],
  savedOrder: string[],
  laneId: string,
  beforeLaneId: string,
): string[] {
  const ids = [...visibleIds];
  const from = ids.indexOf(laneId);
  const to = ids.indexOf(beforeLaneId);
  if (from === -1 || to === -1 || from === to) return savedOrder;

  ids.splice(to, 0, ...ids.splice(from, 1));
  const absent = savedOrder.filter((id) => !ids.includes(id));
  return [...ids, ...absent];
}
