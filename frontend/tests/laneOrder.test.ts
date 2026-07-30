import { describe, expect, it } from 'vitest';
import { applyLaneOrder, moveLaneBefore } from '../src/utilities/laneOrder';

const lane = (id: string) => ({ id });

describe('applyLaneOrder', () => {
  it('uses the saved order', () => {
    const lanes = [lane('activity'), lane('sleep'), lane('heart_rate')];
    const ordered = applyLaneOrder(lanes, ['sleep', 'heart_rate', 'activity']);
    expect(ordered.map((item) => item.id)).toEqual(['sleep', 'heart_rate', 'activity']);
  });

  it('leaves the payload order alone when nothing is saved', () => {
    const lanes = [lane('activity'), lane('sleep')];
    expect(applyLaneOrder(lanes, []).map((item) => item.id)).toEqual(['activity', 'sleep']);
  });

  it('sends a lane the user has never arranged to the bottom', () => {
    // A source starts reporting a new lane: it must not jump to the top.
    const lanes = [lane('location'), lane('activity'), lane('sleep')];
    const ordered = applyLaneOrder(lanes, ['sleep', 'activity']);
    expect(ordered.map((item) => item.id)).toEqual(['sleep', 'activity', 'location']);
  });

  it('keeps several unknown lanes in the order the payload gave them', () => {
    const lanes = [lane('a'), lane('b'), lane('c')];
    expect(applyLaneOrder(lanes, []).map((item) => item.id)).toEqual(['a', 'b', 'c']);
  });

  it('ignores saved ids for lanes this day does not have', () => {
    const lanes = [lane('sleep'), lane('activity')];
    const ordered = applyLaneOrder(lanes, ['hrv', 'activity', 'temperature', 'sleep']);
    expect(ordered.map((item) => item.id)).toEqual(['activity', 'sleep']);
  });

  it('does not mutate the array it was given', () => {
    const lanes = [lane('activity'), lane('sleep')];
    applyLaneOrder(lanes, ['sleep', 'activity']);
    expect(lanes.map((item) => item.id)).toEqual(['activity', 'sleep']);
  });
});

describe('moveLaneBefore', () => {
  const visible = ['activity', 'heart_rate', 'sleep'];

  it('moves a lane down to its neighbour', () => {
    expect(moveLaneBefore(visible, visible, 'activity', 'heart_rate')).toEqual([
      'heart_rate',
      'activity',
      'sleep',
    ]);
  });

  it('moves a lane up to its neighbour', () => {
    expect(moveLaneBefore(visible, visible, 'sleep', 'heart_rate')).toEqual([
      'activity',
      'sleep',
      'heart_rate',
    ]);
  });

  it('moves a lane across several positions in one drop', () => {
    expect(moveLaneBefore(visible, visible, 'sleep', 'activity')).toEqual([
      'sleep',
      'activity',
      'heart_rate',
    ]);
  });

  it('keeps lanes that are absent today rather than erasing them', () => {
    // hrv had no data today, so it is not on screen — but the user arranged it
    // once, and coming back tomorrow it should still be where they put it.
    const saved = ['activity', 'hrv', 'heart_rate', 'sleep'];
    const result = moveLaneBefore(visible, saved, 'sleep', 'activity');
    expect(result).toContain('hrv');
    expect(result.filter((id) => visible.includes(id))).toEqual([
      'sleep',
      'activity',
      'heart_rate',
    ]);
  });

  it('is a no-op when the lane is dropped on itself', () => {
    expect(moveLaneBefore(visible, visible, 'sleep', 'sleep')).toEqual(visible);
  });

  it('is a no-op for an unknown lane', () => {
    expect(moveLaneBefore(visible, visible, 'ghost', 'sleep')).toEqual(visible);
  });

  it('round-trips: moving down then back up restores the order', () => {
    const down = moveLaneBefore(visible, visible, 'activity', 'heart_rate');
    const up = moveLaneBefore(down, down, 'activity', 'heart_rate');
    expect(up).toEqual(visible);
  });
});
