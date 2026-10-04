import { Component, computed, inject, input, output, signal } from '@angular/core';
import { t } from '../i18n/i18n';
import { Session } from '../session';
import { Notice } from '../ui/notice';
import { MAX_COMMENT_LENGTH, actionProblem } from './incident-presentation';
import { IncidentsApi } from './incidents.api';

/**
 * Comment on an incident (VIG-35), responder and above, also once it is resolved: what
 * happened afterwards is worth recording. The comment appears in the timeline below.
 */
@Component({
  selector: 'app-incident-comment',
  imports: [Notice],
  template: `
    @if (allowed()) {
      <form class="mb-6" (submit)="$event.preventDefault(); submit()">
        <label for="comment-text" class="text-sm font-medium text-slate-700">
          {{ t('incidents.comment.label') }}
        </label>
        <textarea
          id="comment-text"
          rows="3"
          class="field mt-1.5 w-full"
          [attr.maxlength]="max"
          aria-describedby="comment-count"
          [value]="text()"
          (input)="text.set($any($event.target).value)"
        ></textarea>
        <div class="mt-2 flex items-center justify-between gap-2">
          <span id="comment-count" class="text-xs text-slate-500">
            {{ t('incidents.comment.count', { length: length(), max }) }}
          </span>
          <button type="submit" class="btn-primary" [disabled]="length() === 0 || busy()">
            {{ t('incidents.comment.submit') }}
          </button>
        </div>
        @if (problem(); as message) {
          <app-notice class="mt-3">{{ message }}</app-notice>
        }
        <p class="mt-2 text-sm text-slate-700" role="status">{{ done() }}</p>
      </form>
    }
  `,
})
export class IncidentComment {
  readonly incidentId = input.required<string>();
  /** The comment was saved: the page reloads the timeline. */
  readonly changed = output();

  private readonly api = inject(IncidentsApi);
  private readonly session = inject(Session);

  protected readonly max = MAX_COMMENT_LENGTH;
  protected readonly t = t;
  protected readonly allowed = computed(
    () => this.session.me()?.permissions.includes('incidents:acknowledge') ?? false,
  );
  protected readonly text = signal('');
  /** What counts, as for the API: without surrounding spaces. */
  protected readonly length = computed(() => this.text().trim().length);
  protected readonly busy = signal(false);
  protected readonly problem = signal<string | null>(null);
  protected readonly done = signal('');

  protected submit(): void {
    const text = this.text().trim();
    if (!text) return;
    this.busy.set(true);
    this.problem.set(null);
    this.done.set('');
    this.api.comment(this.incidentId(), text).subscribe({
      next: () => {
        this.busy.set(false);
        this.text.set('');
        this.done.set(t('incidents.comment.done'));
        this.changed.emit();
      },
      error: (error: unknown) => {
        this.busy.set(false);
        this.problem.set(actionProblem(error));
      },
    });
  }
}
