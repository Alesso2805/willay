import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { FieldChange } from './audit-presentation';

/**
 * Each changed field, before and after. On creation only the new value; on deletion only the
 * old one, struck through. Strikethrough is not the only cue: screen readers hear "cambió a".
 */
@Component({
  selector: 'app-field-changes',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (changes().length > 0) {
      <dl class="flex flex-col gap-1">
        @for (change of changes(); track change.field) {
          <div class="wrap-anywhere">
            <dt class="inline font-medium text-slate-700">{{ change.field }}:</dt>
            <dd class="ml-1 inline text-slate-600">
              @if (change.before === '—') {
                <span class="text-slate-900">{{ change.after }}</span>
              } @else if (change.after === '—') {
                <span class="line-through decoration-slate-400">{{ change.before }}</span>
                <span class="sr-only">(quitado)</span>
              } @else {
                <span class="line-through decoration-slate-400">{{ change.before }}</span>
                <span aria-hidden="true"> → </span><span class="sr-only"> cambió a </span>
                <span class="text-slate-900">{{ change.after }}</span>
              }
            </dd>
          </div>
        }
      </dl>
    } @else {
      <span class="text-slate-500">Sin cambios de campos</span>
    }
  `,
})
export class FieldChanges {
  readonly changes = input.required<FieldChange[]>();
}
