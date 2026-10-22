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
import { currentLocale, t } from '../i18n/i18n';
import { localTime, measurement } from '../ui/formats';
import { ChartPoint, linePath, niceTicks, scale, splitAtGaps, timeTicks } from './chart-scale';
import { IncidentReadings } from './incidents.api';
import { operatorText } from './timeline-presentation';

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
/** Few points (such as the evidence copy) are drawn as dots too, or a short line is easy to miss. */
const MAX_DOTS = 60;
/** The time axis spans at least two minutes, so it always shows an HH:MM label. */
const MIN_SPAN = 2 * 60_000;
/** Room around the data on the time axis: 5 % of its span, at least 30 s. */
const MARGIN_SHARE = 0.05;
const MIN_MARGIN = 30_000;

let nextId = 0;

/**
 * The readings around an incident's opening as an SVG line (own SVG: no chart library).
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
    const windowStart = Date.parse(data.window_start);
    const windowEnd = Date.parse(data.window_end);
    const markTimes = this.marks()
      .map((mark) => Date.parse(mark.at))
      .filter((t) => t >= windowStart && t <= windowEnd);
    // The time axis fits the readings and the marks, not the whole window: a station that
    // reported for one minute of a three-hour window would shrink into a sliver.
    const times = [...points.map((p) => p.t), ...markTimes];
    let first = times.length > 0 ? Math.min(...times) : windowStart;
    let last = times.length > 0 ? Math.max(...times) : windowEnd;
    if (last - first < MIN_SPAN) {
      const middle = (first + last) / 2;
      [first, last] = [middle - MIN_SPAN / 2, middle + MIN_SPAN / 2];
    }
    const margin = Math.max((last - first) * MARGIN_SHARE, MIN_MARGIN);
    const t0 = first - margin;
    const t1 = last + margin;
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
      .filter((mark) => mark.t >= windowStart && mark.t <= windowEnd)
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
            label: `${t('chart.threshold', {
              operator: operatorText(data.threshold.operator),
              value: measurement(data.threshold.value),
            })} ${unit}`.trim(),
          }
        : null,
      marks,
      summary: this.summary(points, windowStart, windowEnd, unit),
    };
  });

  protected readonly t = t;

  protected station(): string {
    return this.data().station_code ?? t('chart.theStation');
  }

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
    return new Intl.DateTimeFormat(currentLocale(), {
      timeZone: this.timezone(),
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).format(t);
  }

  /** What the chart shows, in words: the accessible description of the image. */
  private summary(points: ChartPoint[], windowStart: number, windowEnd: number, unit: string): string {
    const station = this.station();
    if (points.length === 0) {
      return t('chart.empty', {
        station,
        from: this.clock(windowStart),
        to: this.clock(windowEnd),
      });
    }
    const values = points.map((p) => p.value);
    const from = this.clock(points[0].t);
    const to = this.clock(points[points.length - 1].t);
    const when = from === to ? t('chart.at', { time: from }) : t('chart.between', { from, to });
    const range = t('chart.range', {
      min: measurement(Math.min(...values)),
      max: measurement(Math.max(...values)),
    });
    const parts = [
      t('chart.readings', { count: values.length, station, when }),
      `${range} ${unit}`.trim(),
    ];
    const threshold = this.data().threshold;
    if (threshold) {
      const limit = t('chart.thresholdShort', {
        operator: operatorText(threshold.operator),
        value: measurement(threshold.value),
      });
      parts.push(`${limit} ${unit}`.trim());
    }
    return `${parts.join('; ')}.`;
  }
}
