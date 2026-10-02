import {
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { localTime, measurement } from '../ui/formats';
import { ChartPoint, linePath, niceTicks, scale, splitAtGaps, timeTicks } from './chart-scale';
import { IncidentReadings } from './incidents.api';

/** A moment to mark on the chart, such as the opening or the acknowledgement. */
export interface ChartMark {
  at: string;
  label: string;
}

/** Width before the first measurement, and in tests (jsdom has no ResizeObserver). */
const DEFAULT_WIDTH = 640;
const MIN_WIDTH = 280;
const H = 240;
const M = { top: 34, right: 16, bottom: 26, left: 52 };
const OPERATORS: Record<string, string> = { gt: 'más de', ge: 'desde', lt: 'menos de', le: 'hasta' };
/** Few points (such as the evidence copy) are drawn as dots too, or a short line is easy to miss. */
const MAX_DOTS = 60;

let nextId = 0;

/**
 * The readings around an incident's opening as an SVG line (VIG-26, own SVG: no chart library).
 * Screen readers get a text summary, and "Ver como tabla" shows every reading.
 */
@Component({
  selector: 'app-readings-chart',
  host: { class: 'block' },
  templateUrl: './readings-chart.html',
})
export class ReadingsChart {
  readonly data = input.required<IncidentReadings>();
  readonly marks = input<ChartMark[]>([]);
  readonly timezone = input('UTC');

  /**
   * The SVG is drawn at the width it really has, not scaled: scaling a 640-wide drawing down to
   * a phone would shrink its text to a few pixels.
   */
  protected readonly width = signal(DEFAULT_WIDTH);
  protected readonly H = H;
  protected readonly M = M;
  protected readonly id = `readings-chart-${nextId++}`;
  protected readonly showTable = signal(false);

  private readonly points = computed<ChartPoint[]>(() =>
    this.data().readings.map((r) => ({ t: Date.parse(r.measured_at), value: r.value })),
  );

  constructor() {
    const host = inject(ElementRef<HTMLElement>).nativeElement as HTMLElement;
    const destroyRef = inject(DestroyRef);
    afterNextRender(() => {
      if (typeof ResizeObserver === 'undefined') return;
      const observer = new ResizeObserver(([entry]) =>
        this.width.set(Math.max(MIN_WIDTH, Math.round(entry.contentRect.width))),
      );
      observer.observe(host);
      destroyRef.onDestroy(() => observer.disconnect());
    });
  }

  protected readonly model = computed(() => {
    const W = this.width();
    const data = this.data();
    const points = this.points();
    const unit = data.unit ?? '';
    // The window, widened if the evidence copy falls outside it.
    const t0 = Math.min(Date.parse(data.window_start), ...points.map((p) => p.t));
    const t1 = Math.max(Date.parse(data.window_end), ...points.map((p) => p.t));
    const readings = points.map((p) => p.value);
    // The threshold line must fit in the axis too, even if no reading reached it.
    const values = data.threshold ? [...readings, data.threshold.value] : readings;
    const yTicks = values.length > 0 ? niceTicks(Math.min(...values), Math.max(...values)) : [0, 1];
    const x = scale([t0, t1], [M.left, W - M.right]);
    const y = scale([yTicks[0], yTicks[yTicks.length - 1]], [H - M.bottom, M.top]);

    let labelY = 12;
    let lastX = -Infinity;
    const marks = this.marks()
      .map((mark) => ({ ...mark, t: Date.parse(mark.at) }))
      .filter((mark) => mark.t >= t0 && mark.t <= t1)
      .sort((a, b) => a.t - b.t)
      .map((mark) => {
        const mx = x(mark.t);
        labelY = mx - lastX < 90 ? labelY + 12 : 12; // close marks: stack their labels
        lastX = mx;
        return { x: mx, label: mark.label, labelY, anchor: mx > W - 120 ? 'end' : 'start' };
      });

    return {
      paths: splitAtGaps(points).map((run) => linePath(run.map((p) => [x(p.t), y(p.value)]))),
      dots: points.length <= MAX_DOTS ? points.map((p) => ({ x: x(p.t), y: y(p.value) })) : [],
      yTicks: yTicks.map((v) => ({ y: y(v), label: measurement(v) })),
      // About one time label per 130 px, so they never overlap on a phone.
      xTicks: timeTicks(t0, t1, Math.max(2, Math.floor(W / 130))).map((t) => ({
        x: x(t),
        label: this.clock(t),
      })),
      threshold: data.threshold
        ? {
            y: y(data.threshold.value),
            label: `Umbral: ${OPERATORS[data.threshold.operator] ?? data.threshold.operator} ${measurement(data.threshold.value)} ${unit}`.trim(),
          }
        : null,
      marks,
      summary: this.summary(readings, t0, t1, unit),
    };
  });

  protected toggleTable(): void {
    this.showTable.update((shown) => !shown);
  }

  protected time(iso: string): string {
    return localTime(iso, this.timezone(), true);
  }

  protected number(value: number): string {
    return measurement(value);
  }

  /** "HH:MM" in the organization's time zone, for the time axis. */
  private clock(t: number): string {
    return new Intl.DateTimeFormat('es-PE', {
      timeZone: this.timezone(),
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).format(t);
  }

  /** What the chart shows, in words: the accessible description of the image. */
  private summary(values: number[], t0: number, t1: number, unit: string): string {
    const station = this.data().station_code ?? 'la estación';
    if (values.length === 0) return `Sin lecturas de ${station} entre ${this.clock(t0)} y ${this.clock(t1)}.`;
    const range = `mínimo ${measurement(Math.min(...values))} y máximo ${measurement(Math.max(...values))} ${unit}`.trim();
    const parts = [
      `${values.length} ${values.length === 1 ? 'lectura' : 'lecturas'} de ${station} entre ${this.clock(t0)} y ${this.clock(t1)}`,
      range,
    ];
    const threshold = this.data().threshold;
    if (threshold) {
      parts.push(`umbral ${OPERATORS[threshold.operator] ?? threshold.operator} ${measurement(threshold.value)} ${unit}`.trim());
    }
    return `${parts.join('; ')}.`;
  }
}
