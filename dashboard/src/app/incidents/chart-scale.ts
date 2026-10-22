/** Pure helpers for the readings chart: axes, scales and the line, with no Angular. */

export interface ChartPoint {
  /** Epoch milliseconds. */
  t: number;
  value: number;
}

/** Maps a domain onto a range, linearly; a zero-width domain maps to the start of the range. */
export function scale(domain: [number, number], range: [number, number]): (v: number) => number {
  const span = domain[1] - domain[0];
  return (v) => (span === 0 ? range[0] : range[0] + ((v - domain[0]) / span) * (range[1] - range[0]));
}

/** Round values for a value axis (1, 2 or 5 times a power of ten) covering [min, max]. */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const raw = (max - min) / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? 10 * power;
  const ticks: number[] = [];
  for (let v = Math.floor(min / step) * step; v <= max + step * 0.999; v += step) {
    ticks.push(Number(v.toPrecision(12))); // 0.30000000000000004 → 0.3
  }
  return ticks;
}

const MINUTE = 60_000;
const TIME_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 180, 360, 720].map((m) => m * MINUTE);

/** Round times for the time axis, aligned to whole minutes or hours. */
export function timeTicks(start: number, end: number, count = 5): number[] {
  const raw = (end - start) / count;
  const step = TIME_STEPS.find((s) => s >= raw) ?? TIME_STEPS[TIME_STEPS.length - 1];
  const ticks: number[] = [];
  for (let t = Math.ceil(start / step) * step; t <= end; t += step) ticks.push(t);
  return ticks;
}

/**
 * The points as separate runs wherever two readings are further apart than `factor` times the
 * usual spacing: a line across a silence would draw data that does not exist.
 */
export function splitAtGaps(points: readonly ChartPoint[], factor = 3): ChartPoint[][] {
  if (points.length < 3) return points.length > 0 ? [[...points]] : [];
  const gaps = points.slice(1).map((p, i) => p.t - points[i].t);
  const usual = [...gaps].sort((a, b) => a - b)[Math.floor(gaps.length / 2)];
  const runs: ChartPoint[][] = [[points[0]]];
  gaps.forEach((gap, i) => {
    if (gap > usual * factor) runs.push([]);
    runs[runs.length - 1].push(points[i + 1]);
  });
  return runs;
}

/** An SVG path through already scaled coordinates. */
export function linePath(coordinates: readonly [number, number][]): string {
  return coordinates
    .map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(' ');
}
