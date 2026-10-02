import { linePath, niceTicks, scale, splitAtGaps, timeTicks } from './chart-scale';

const MIN = 60_000;

describe('chart scale', () => {
  it('maps values linearly, upside down for an SVG y axis', () => {
    const y = scale([0, 10], [200, 0]);
    expect(y(0)).toBe(200);
    expect(y(5)).toBe(100);
    expect(y(10)).toBe(0);
    expect(scale([3, 3], [200, 0])(3)).toBe(200);
  });

  it('chooses round value ticks that cover the data', () => {
    // About 4 steps of 1, 2 or 5 times a power of ten, from below the minimum to above the maximum.
    expect(niceTicks(2.0, 4.6)).toEqual([2, 3, 4, 5]);
    expect(niceTicks(80, 90)).toEqual([80, 85, 90]);
    expect(niceTicks(0.1, 0.3)).toEqual([0.1, 0.15, 0.2, 0.25, 0.3]); // no 0.15000000000000002
    const flat = niceTicks(5, 5);
    expect(flat[0]).toBeLessThan(5);
    expect(flat[flat.length - 1]).toBeGreaterThan(5);
  });

  it('chooses time ticks on whole minutes or hours', () => {
    const start = Date.parse('2026-10-02T02:31:00Z');
    const end = Date.parse('2026-10-02T05:31:00Z');
    expect(timeTicks(start, end).map((t) => new Date(t).toISOString().slice(11, 16))).toEqual([
      '03:00',
      '04:00',
      '05:00',
    ]);
    const short = timeTicks(start, start + 20 * MIN);
    expect(short.every((t) => t % (5 * MIN) === 0)).toBe(true);
  });

  it('breaks the line where readings stop for a while', () => {
    const at = (minutes: number) => ({ t: minutes * MIN, value: 1 });
    const runs = splitAtGaps([at(0), at(1), at(2), at(3), at(30), at(31), at(32)]);
    expect(runs.map((run) => run.length)).toEqual([4, 3]);
    expect(splitAtGaps([at(0), at(1)])).toHaveLength(1);
    expect(splitAtGaps([])).toEqual([]);
  });

  it('draws a path through scaled points', () => {
    expect(linePath([[0, 10], [5.25, 2]])).toBe('M0.0 10.0 L5.3 2.0');
  });
});
