import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { t } from '../i18n/i18n';
import { Icon } from './icon';
import { VisualState } from './visual-states';

@Component({
  selector: 'app-state-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon],
  template: `
    <span
      class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap"
      [style.color]="state().foreground"
      [style.background-color]="state().background"
    >
      <app-icon [name]="state().icon" [size]="14" />
      {{ t(state().labelKey) }}
    </span>
  `,
})
export class StateBadge {
  readonly state = input.required<VisualState>();
  protected readonly t = t;
}
