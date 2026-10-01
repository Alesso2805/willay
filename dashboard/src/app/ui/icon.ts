import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/**
 * Íconos de trazo en una cuadrícula de 24 × 24, dibujados aquí para no sumar una
 * dependencia. Son decorativos (`aria-hidden`): el significado siempre va en texto al lado.
 */
const CIRCLE = 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z';
const OCTAGON = 'M7.86 2h8.28L22 7.86v8.28L16.14 22H7.86L2 16.14V7.86z';
const TRIANGLE = 'M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z';
const BELL = 'M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0';
const WIFI = 'M5 12.55a11 11 0 0 1 14.08 0M1.42 9a16 16 0 0 1 21.16 0M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01';
const PIN = 'M12 22s7-6.3 7-12a7 7 0 0 0-14 0c0 5.7 7 12 7 12zM14.5 10a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z';
const SLASH = 'M2 2l20 20';
const BAR = ['M5 20v-3', 'M10 20v-7', 'M15 20v-11', 'M20 20v-15'];

export const ICONS = {
  bell: [BELL],
  check: ['M5 12l5 5L20 7'],
  'check-circle': [CIRCLE, 'M8 12l3 3 5-6'],
  'octagon-x': [OCTAGON, 'M15 9l-6 6', 'M9 9l6 6'],
  'octagon-alert': [OCTAGON, 'M12 8v4', 'M12 16h.01'],
  'triangle-alert': [TRIANGLE, 'M12 9v4', 'M12 17h.01'],
  info: [CIRCLE, 'M12 16v-4', 'M12 8h.01'],
  'level-1': ['M3 21h18', ...BAR.slice(0, 1)],
  'level-2': ['M3 21h18', ...BAR.slice(0, 2)],
  'level-3': ['M3 21h18', ...BAR.slice(0, 3)],
  'level-4': ['M3 21h18', ...BAR],
  signal: [WIFI],
  'signal-off': [WIFI, SLASH],
  'pin-off': [PIN, SLASH],
  pause: ['M8 5v14', 'M16 5v14'],
} as const satisfies Record<string, readonly string[]>;

export type IconName = keyof typeof ICONS;

@Component({
  selector: 'app-icon',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'inline-flex shrink-0' },
  template: `
    <svg
      viewBox="0 0 24 24"
      [attr.width]="size()"
      [attr.height]="size()"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      @for (d of paths(); track $index) {
        <path [attr.d]="d" />
      }
    </svg>
  `,
})
export class Icon {
  readonly name = input.required<IconName>();
  readonly size = input(16);
  protected readonly paths = computed(() => ICONS[this.name()]);
}
