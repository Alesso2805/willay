import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** Page title, a short summary and its actions on the right (VIG-33). */
@Component({
  selector: 'app-page-header',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'mb-6 flex flex-wrap items-end justify-between gap-4' },
  template: `
    <div class="min-w-0">
      <h1 class="text-2xl font-semibold tracking-tight text-slate-900">{{ title() }}</h1>
      @if (subtitle()) {
        <p class="mt-1 text-sm text-slate-500">{{ subtitle() }}</p>
      }
    </div>
    <div class="flex flex-wrap items-center gap-3">
      <ng-content />
    </div>
  `,
})
export class PageHeader {
  readonly title = input.required<string>();
  readonly subtitle = input<string>('');
}
