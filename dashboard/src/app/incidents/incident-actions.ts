import { HttpErrorResponse } from '@angular/common/http';
import {
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { t } from '../i18n/i18n';
import { Session } from '../session';
import { Notice } from '../ui/notice';
import { actionProblem } from './incident-presentation';
import { IncidentDetail, IncidentsApi } from './incidents.api';

type Resolution = 'resolved' | 'false_alarm';

/**
 * Acknowledge and resolve from the incident detail. The buttons follow the user's
 * permissions (acknowledge: responder and above; resolve: operator and above); the API checks
 * them anyway. Resolving is final, so it asks how it ended and to confirm, in a panel inside
 * the card that leaves the timeline in view.
 */
@Component({
  selector: 'app-incident-actions',
  imports: [Notice],
  template: `
    @if (!mayAct()) {
      <p class="text-sm text-ink-muted">{{ t('incidents.actions.viewOnly') }}</p>
    } @else if (!canAcknowledge() && !canResolve()) {
      <p class="text-sm text-ink-muted">
        @if (incident().status === 'resolved') {
          {{ t('incidents.actions.resolvedFinal') }}
        } @else {
          {{ t('incidents.actions.operatorResolves') }}
        }
      </p>
    } @else {
      <div class="flex flex-wrap gap-2">
        @if (canAcknowledge()) {
          <button type="button" class="btn-primary" [disabled]="busy()" (click)="acknowledge()">
            {{ t('incidents.actions.acknowledge') }}
          </button>
        }
        @if (canResolve() && !resolving()) {
          <button
            type="button"
            class="btn-secondary"
            [disabled]="busy()"
            aria-controls="resolve-panel"
            [attr.aria-expanded]="resolving()"
            (click)="openResolve()"
          >
            {{ t('incidents.actions.resolve') }}
          </button>
        }
      </div>

      @if (resolving()) {
        <form
          id="resolve-panel"
          class="mt-4 rounded-lg border border-line p-4"
          (submit)="$event.preventDefault(); resolve()"
        >
          <fieldset>
            <legend class="text-sm font-medium text-ink">{{ t('incidents.actions.howEnded') }}</legend>
            <label class="mt-3 flex items-start gap-2 text-sm">
              <input
                #firstOption
                type="radio"
                name="resolution"
                value="resolved"
                class="mt-1 accent-brand-700"
                (change)="resolution.set('resolved')"
              />
              <span>
                <span class="font-medium text-ink">{{ t('incidents.actions.resolved') }}</span>
                <span class="block text-ink-muted">{{ t('incidents.actions.resolvedHint') }}</span>
              </span>
            </label>
            <label class="mt-2 flex items-start gap-2 text-sm">
              <input
                type="radio"
                name="resolution"
                value="false_alarm"
                class="mt-1 accent-brand-700"
                (change)="resolution.set('false_alarm')"
              />
              <span>
                <span class="font-medium text-ink">{{ t('incidents.actions.falseAlarm') }}</span>
                <span class="block text-ink-muted">{{ t('incidents.actions.falseAlarmHint') }}</span>
              </span>
            </label>
          </fieldset>
          <p class="mt-3 text-sm text-ink-soft">{{ t('incidents.actions.finalWarning') }}</p>
          <div class="mt-3 flex flex-wrap gap-2">
            <button type="submit" class="btn-primary" [disabled]="!resolution() || busy()">
              {{ t('incidents.actions.resolveFinal') }}
            </button>
            <button type="button" class="btn-secondary" (click)="cancelResolve()">
              {{ t('incidents.actions.cancel') }}
            </button>
          </div>
        </form>
      }
    }

    @if (problem(); as text) {
      <app-notice class="mt-3">{{ text }}</app-notice>
    }
    <p class="mt-2 text-sm text-ink-soft" role="status">{{ done() }}</p>
  `,
})
export class IncidentActions {
  readonly incident = input.required<IncidentDetail>();
  /** Something changed (or someone got there first): the page reloads the incident. */
  readonly changed = output();

  private readonly api = inject(IncidentsApi);
  private readonly session = inject(Session);
  protected readonly t = t;
  private readonly injector = inject(Injector);
  private readonly firstOption = viewChild<ElementRef<HTMLInputElement>>('firstOption');

  private readonly permissions = computed(() => this.session.me()?.permissions ?? []);
  protected readonly mayAct = computed(
    () =>
      this.permissions().includes('incidents:acknowledge') ||
      this.permissions().includes('incidents:resolve'),
  );
  protected readonly canAcknowledge = computed(
    () =>
      this.incident().status === 'open' && this.permissions().includes('incidents:acknowledge'),
  );
  protected readonly canResolve = computed(
    () => this.incident().status !== 'resolved' && this.permissions().includes('incidents:resolve'),
  );

  protected readonly resolving = signal(false);
  protected readonly resolution = signal<Resolution | null>(null);
  protected readonly busy = signal(false);
  protected readonly problem = signal<string | null>(null);
  protected readonly done = signal('');

  protected acknowledge(): void {
    this.start();
    this.api.acknowledge(this.incident().id).subscribe({
      next: () => this.finish(t('incidents.actions.doneAcknowledged')),
      error: (error: unknown) => this.failed(error),
    });
  }

  protected openResolve(): void {
    this.resolution.set(null);
    this.problem.set(null);
    this.resolving.set(true);
    // Keyboard and screen reader users land on the first choice, not back at the top.
    afterNextRender(() => this.firstOption()?.nativeElement.focus(), { injector: this.injector });
  }

  protected cancelResolve(): void {
    this.resolving.set(false);
  }

  protected resolve(): void {
    const resolution = this.resolution();
    if (!resolution) return;
    this.start();
    this.api.resolve(this.incident().id, resolution).subscribe({
      next: () => {
        this.resolving.set(false);
        this.finish(
          t(
            resolution === 'false_alarm'
              ? 'incidents.actions.doneFalseAlarm'
              : 'incidents.actions.doneResolved',
          ),
        );
      },
      error: (error: unknown) => this.failed(error),
    });
  }

  private start(): void {
    this.busy.set(true);
    this.problem.set(null);
    this.done.set('');
  }

  private finish(message: string): void {
    this.busy.set(false);
    this.done.set(message);
    this.changed.emit();
  }

  private failed(error: unknown): void {
    this.busy.set(false);
    this.problem.set(actionProblem(error));
    if (error instanceof HttpErrorResponse && error.status === 409) {
      this.resolving.set(false);
      this.changed.emit(); // show what the incident is now
    }
  }
}
