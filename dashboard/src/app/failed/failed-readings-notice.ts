import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { EMPTY, catchError, merge, of, switchMap } from 'rxjs';
import { LiveEvents } from '../realtime/live-events';
import { Session } from '../session';
import { Notice } from '../ui/notice';
import { FailedReadingsApi } from './failed-readings.api';

/**
 * On every page, while any reading failed evaluation (VIG-39): each one may be an alert that
 * did not go out. Only for those who can reprocess them. The count is refetched when the live
 * channel says it changed, and whenever pages reload (reconnection, or every 15 s offline).
 */
@Component({
  selector: 'app-failed-readings-notice',
  imports: [RouterLink, Notice],
  template: `
    @if (count() > 0) {
      <app-notice tone="warning" class="mb-6">
        {{ text() }}
        <a routerLink="/lecturas-fallidas" class="font-semibold underline">Ver lecturas fallidas</a>
      </app-notice>
    }
  `,
})
export class FailedReadingsNotice {
  private readonly api = inject(FailedReadingsApi);
  private readonly live = inject(LiveEvents);
  private readonly session = inject(Session);

  protected readonly count = signal(0);
  protected readonly text = computed(() =>
    this.count() === 1
      ? '1 lectura no se pudo evaluar: puede ser una alerta que no salió.'
      : `${this.count()} lecturas no se pudieron evaluar: puede haber alertas que no salieron.`,
  );

  constructor() {
    if (!this.session.me()?.permissions.includes('readings:reprocess')) return;
    // switchMap: only the latest count counts, even if an older request answers later.
    merge(of(undefined), this.live.reload$, this.live.failedReadings$)
      .pipe(
        switchMap(() => this.api.count().pipe(catchError(() => EMPTY))),
        takeUntilDestroyed(),
      )
      .subscribe(({ count }) => this.count.set(count));
  }
}
