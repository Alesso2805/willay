import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslationKey, t } from '../i18n/i18n';
import { Session } from '../session';
import { settings } from '../settings';
import { clock } from '../ui/clock';
import { localTime } from '../ui/formats';
import { Icon } from '../ui/icon';
import { Notice } from '../ui/notice';
import { Demo, DemoApi, DemoPhase } from './demo.api';

const ACTIVE_POLL_MS = 3_000;
const IDLE_POLL_MS = 30_000;

const PHASES: Readonly<Record<DemoPhase, TranslationKey>> = {
  normal: 'demo.phases.normal',
  drop: 'demo.phases.drop',
  silence: 'demo.phases.silence',
  done: 'demo.phases.done',
};

type StepState = 'done' | 'current' | 'upcoming';

/** Said to screen readers next to each step: its icon and highlight are not enough. */
const STEP_STATES: Readonly<Record<StepState, TranslationKey>> = {
  done: 'demo.stepState.done',
  current: 'demo.stepState.current',
  upcoming: 'demo.stepState.upcoming',
};

/** m:ss, as a stopwatch: 75 -> "1:15". */
export function stopwatch(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

/**
 * The public demo's panel on Inicio (VIG-43): what the Rímac scenario does, the button that
 * starts it (demo admin) and its progress, for every user of the demo organization. It asks
 * every 3 s while a run is on and every 30 s otherwise, so a run someone else started shows up.
 */
@Component({
  selector: 'app-demo-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon, Notice, RouterLink],
  template: `
    @if (demo(); as demo) {
      @if (demo.available) {
        <section class="card mb-6 p-5" aria-labelledby="demo-title">
          <div class="flex flex-wrap items-start justify-between gap-4">
            <div class="max-w-2xl">
              <h2 id="demo-title" class="font-semibold text-ink">{{ t('demo.title') }}</h2>
              <p class="mt-1 text-sm text-ink-muted">{{ t('demo.intro') }}</p>
            </div>
            <div class="flex flex-wrap items-center gap-3">
              <a class="link-action text-sm" [href]="mailUrl" target="_blank" rel="noopener">
                {{ t('demo.mail') }}
              </a>
              @if (demo.can_run) {
                <button
                  type="button"
                  class="btn-primary"
                  [disabled]="busy() || active()"
                  (click)="start()"
                >
                  <app-icon name="play" />
                  {{ t('demo.run') }}
                </button>
              }
            </div>
          </div>

          <!-- Only what changes in steps is announced: the clock would speak every second. -->
          <p class="sr-only" aria-live="polite">{{ announcement() }}</p>

          @if (restoring()) {
            <app-notice tone="info" class="mt-4">{{ t('demo.restoring') }}</app-notice>
          } @else if (playing()) {
            <p class="mt-4 text-sm font-medium text-ink">
              {{
                queued()
                  ? t('demo.queued')
                  : t('demo.playing', { elapsed: elapsedText(), total: totalText() })
              }}
            </p>
            <ol class="mt-3 grid gap-2 sm:grid-cols-4">
              @for (step of steps(); track step.phase) {
                <li
                  class="rounded-lg p-3 text-sm ring-1"
                  [class]="
                    step.state === 'current'
                      ? 'bg-accent-soft text-ink ring-accent'
                      : 'text-ink-muted ring-line'
                  "
                  [attr.aria-current]="step.state === 'current' ? 'step' : null"
                >
                  <span class="flex items-center gap-1.5 font-medium">
                    <app-icon [name]="step.state === 'done' ? 'check' : 'clock'" [size]="14" />
                    {{ step.at }}
                    <span class="sr-only">{{ t(stepStates[step.state]) }}</span>
                  </span>
                  <span class="mt-1 block">{{ t(step.label) }}</span>
                </li>
              }
            </ol>
            <p class="mt-3 text-sm text-ink-muted">
              {{ t('demo.whilePlaying') }}
              <a routerLink="/mapa" class="link-action">{{ t('demo.toMap') }}</a>
            </p>
          } @else if (demo.run?.status === 'done' && demo.run?.finished_at) {
            <p class="mt-4 text-sm text-ink-muted">
              {{ t('demo.finished', { time: finishedAt() }) }}
              <a routerLink="/incidentes" class="link-action">{{ t('demo.toIncidents') }}</a>
            </p>
          } @else if (demo.run?.status === 'failed') {
            <app-notice tone="warning" class="mt-4">{{ t('demo.failed') }}</app-notice>
          }

          @if (problem(); as problem) {
            <app-notice class="mt-4">{{ problem }}</app-notice>
          }
        </section>
      }
    }
  `,
})
export class DemoPanel {
  private readonly api = inject(DemoApi);
  private readonly session = inject(Session);
  protected readonly t = t;
  protected readonly mailUrl = settings.mailUrl;
  protected readonly stepStates = STEP_STATES;
  protected readonly demo = signal<Demo | null>(null);
  protected readonly busy = signal(false);
  protected readonly problem = signal<string | null>(null);
  private readonly now = clock(1_000);
  private readonly fetchedAt = signal(Date.now());

  private readonly run = computed(() => this.demo()?.run ?? null);
  protected readonly active = computed(() => {
    const status = this.run()?.status;
    return status === 'queued' || status === 'running';
  });
  protected readonly restoring = computed(() => this.active() && this.run()?.kind === 'restore');
  protected readonly playing = computed(() => this.active() && this.run()?.kind === 'scenario');
  protected readonly queued = computed(() => this.run()?.status === 'queued');
  /** The server's elapsed time, moved on by the browser clock between two answers. */
  private readonly elapsed = computed(() => {
    const run = this.run();
    if (run?.elapsed_s == null) return 0;
    return run.elapsed_s + Math.max(0, (this.now() - this.fetchedAt()) / 1000);
  });
  protected readonly elapsedText = computed(() => stopwatch(this.elapsed()));
  protected readonly totalText = computed(() => stopwatch(this.demo()?.duration_s ?? 0));
  protected readonly steps = computed(() => {
    const demo = this.demo();
    if (!demo) return [];
    const elapsed = this.queued() ? -1 : this.elapsed();
    return demo.timeline.map((step, i) => {
      const next = demo.timeline[i + 1]?.at_s ?? Infinity;
      const state: StepState =
        elapsed >= next ? 'done' : elapsed >= step.at_s ? 'current' : 'upcoming';
      return { phase: step.phase, at: stopwatch(step.at_s), label: PHASES[step.phase], state };
    });
  });
  protected readonly announcement = computed(() => {
    if (this.restoring()) return t('demo.restoring');
    if (!this.playing()) return '';
    if (this.queued()) return t('demo.queued');
    const phase = this.run()?.phase;
    return phase ? t(PHASES[phase]) : '';
  });
  protected readonly finishedAt = computed(() => {
    const finished = this.run()?.finished_at;
    const timezone = this.session.me()?.organization_timezone ?? 'UTC';
    return finished ? localTime(finished, timezone) : '';
  });

  constructor() {
    this.load();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = () => {
      timer = setTimeout(
        () => {
          this.load();
          schedule();
        },
        this.active() ? ACTIVE_POLL_MS : IDLE_POLL_MS,
      );
    };
    schedule();
    inject(DestroyRef).onDestroy(() => clearTimeout(timer));
  }

  protected start(): void {
    this.busy.set(true);
    this.problem.set(null);
    this.api.startScenario().subscribe({
      next: () => {
        this.busy.set(false);
        this.load();
      },
      error: (error: unknown) => {
        this.busy.set(false);
        const conflict = error instanceof HttpErrorResponse && error.status === 409;
        this.problem.set(t(conflict ? 'demo.busy' : 'demo.startFailed'));
        this.load();
      },
    });
  }

  private load(): void {
    this.api.get().subscribe({
      next: (demo) => {
        this.fetchedAt.set(Date.now());
        this.demo.set(demo);
      },
      // Not worth a notice: the panel simply stays as it was, or absent.
      error: () => undefined,
    });
  }
}
