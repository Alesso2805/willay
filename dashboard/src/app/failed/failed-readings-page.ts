import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { EMPTY, Subject, catchError, merge, switchMap } from 'rxjs';
import { t } from '../i18n/i18n';
import { LiveEvents } from '../realtime/live-events';
import { Session } from '../session';
import { clock } from '../ui/clock';
import { ageText, localTime, valueWithUnit } from '../ui/formats';
import { LoadState, loadStatus } from '../ui/load-state';
import { Notice } from '../ui/notice';
import { PageHeader } from '../ui/page-header';
import { FailedReading, FailedReadingsApi } from './failed-readings.api';

/**
 * Readings the evaluator gave up on after 5 attempts. Each one may be an alert that did
 * not go out, so the operator reviews the error, fixes the cause and sends them back to the
 * queue. Reached from the notice every page shows while there is any.
 */
@Component({
  selector: 'app-failed-readings-page',
  imports: [LoadState, Notice, PageHeader],
  templateUrl: './failed-readings-page.html',
})
export class FailedReadingsPage {
  private readonly api = inject(FailedReadingsApi);
  private readonly session = inject(Session);
  protected readonly t = t;
  private readonly live = inject(LiveEvents);

  protected readonly readings = signal<FailedReading[]>([]);
  protected readonly loaded = signal(false);
  protected readonly loadFailed = signal(false);
  protected readonly listStatus = computed(() =>
    loadStatus(this.loaded(), this.loadFailed(), this.readings().length),
  );
  protected readonly selected = signal<ReadonlySet<number>>(new Set());
  protected readonly working = signal(false);
  protected readonly status = signal('');
  protected readonly now = clock(30_000);

  protected readonly canReprocess = computed(
    () => this.session.me()?.permissions.includes('readings:reprocess') ?? false,
  );
  protected readonly subtitle = computed(() => {
    if (!this.loaded()) return '';
    const count = this.readings().length;
    return t('failedPage.subtitle', { count });
  });
  protected readonly allSelected = computed(
    () => this.readings().length > 0 && this.selected().size === this.readings().length,
  );
  /** switchMap: only the latest list counts, even if an older request answers later. */
  private readonly loads = new Subject<void>();

  constructor() {
    if (!this.canReprocess()) return;
    this.loads
      .pipe(
        switchMap(() =>
          this.api.list().pipe(
            catchError(() => {
              this.loadFailed.set(true);
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((readings) => {
        this.readings.set(readings);
        // What is no longer failed (reprocessed, here or by someone else) cannot stay selected.
        const ids = new Set(readings.map((r) => r.id));
        this.selected.update((selected) => new Set([...selected].filter((id) => ids.has(id))));
        this.loaded.set(true);
        this.loadFailed.set(false);
      });
    this.load();
    merge(this.live.reload$, this.live.failedReadings$)
      .pipe(takeUntilDestroyed())
      .subscribe(() => this.load());
  }

  protected load(): void {
    this.loads.next();
  }

  protected time(iso: string): string {
    return localTime(iso, this.session.me()?.organization_timezone ?? 'UTC', true);
  }

  protected age(iso: string): string {
    return ageText(iso, this.now());
  }

  protected value(reading: FailedReading): string {
    return reading.value === null
      ? t('failedPage.expired')
      : valueWithUnit(reading.value, reading.unit);
  }

  protected toggle(id: number, checked: boolean): void {
    this.selected.update((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  protected toggleAll(checked: boolean): void {
    this.selected.set(new Set(checked ? this.readings().map((r) => r.id) : []));
  }

  protected reprocess(): void {
    const ids = [...this.selected()];
    if (ids.length === 0) return;
    if (!confirm(t('failedPage.confirm', { count: ids.length }))) return;
    this.working.set(true);
    this.api.reprocess(ids).subscribe({
      next: ({ reprocessed }) => {
        this.working.set(false);
        this.selected.set(new Set());
        this.status.set(t('failedPage.requeued', { count: reprocessed }));
        this.load();
      },
      error: () => {
        this.working.set(false);
        this.status.set(t('failedPage.reprocessFailed'));
      },
    });
  }
}
