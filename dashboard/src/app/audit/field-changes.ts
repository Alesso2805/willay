import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { t } from '../i18n/i18n';
import { FieldChange } from './audit-presentation';

/**
 * Each changed field, before and after. On creation only the new value; on deletion only the
 * old one, struck through. Strikethrough is not the only cue: screen readers also hear
 * `audit.changedTo` on a change and `audit.removed` on a deletion.
 */
@Component({
  selector: 'app-field-changes',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (changes().length > 0) {
      <dl class="flex flex-col gap-1">
        @for (change of changes(); track change.field) {
          <div class="wrap-anywhere">
            <dt class="inline font-medium text-ink-soft">{{ change.field }}:</dt>
            <dd class="ml-1 inline text-ink-muted">
              @if (change.before === '—') {
                <span class="text-ink">{{ change.after }}</span>
              } @else if (change.after === '—') {
                <span class="line-through decoration-ink-subtle">{{ change.before }}</span>
                <span class="sr-only">{{ t('audit.removed') }}</span>
              } @else {
                <span class="line-through decoration-ink-subtle">{{ change.before }}</span>
                <span aria-hidden="true"> → </span><span class="sr-only"> {{ t('audit.changedTo') }} </span>
                <span class="text-ink">{{ change.after }}</span>
              }
            </dd>
          </div>
        }
      </dl>
    } @else {
      <span class="text-ink-subtle">{{ t('audit.noFieldChanges') }}</span>
    }
  `,
})
export class FieldChanges {
  readonly changes = input.required<FieldChange[]>();
  protected readonly t = t;
}
