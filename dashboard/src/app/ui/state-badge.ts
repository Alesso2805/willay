import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { Icon } from './icon';
import { VisualState } from './visual-states';

/** Etiqueta de un estado del catálogo: ícono + texto sobre su color (VIG-33). */
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
      {{ state().label }}
    </span>
  `,
})
export class StateBadge {
  readonly state = input.required<VisualState>();
}
