import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/**
 * Stroke icons on a 24 × 24 grid, drawn here to avoid adding a dependency. They are
 * decorative (`aria-hidden`): the meaning always goes in text next to them.
 */
const CIRCLE = 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z';
const OCTAGON = 'M7.86 2h8.28L22 7.86v8.28L16.14 22H7.86L2 16.14V7.86z';
const TRIANGLE = 'M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z';
const BELL = 'M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0';
const WIFI =
  'M5 12.55a11 11 0 0 1 14.08 0M1.42 9a16 16 0 0 1 21.16 0M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01';
const PIN =
  'M12 22s7-6.3 7-12a7 7 0 0 0-14 0c0 5.7 7 12 7 12zM14.5 10a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z';
const SLASH = 'M2 2l20 20';
const BAR = ['M5 20v-3', 'M10 20v-7', 'M15 20v-11', 'M20 20v-15'];
/** A point with radio waves on both sides. */
const WAVES = [
  'M12 12h.01',
  'M8.5 8.5a5 5 0 0 0 0 7',
  'M15.5 8.5a5 5 0 0 1 0 7',
  'M5.6 5.6a9 9 0 0 0 0 12.8',
  'M18.4 5.6a9 9 0 0 1 0 12.8',
];

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
  broadcast: WAVES,
  refresh: ['M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8', 'M21 3v5h-5'],
  clock: [CIRCLE, 'M12 7v5l3 2'],
  users: [
    'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2',
    'M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0z',
    'M22 21v-2a4 4 0 0 0-3-3.87',
    'M16 3.13a4 4 0 0 1 0 7.75',
  ],
  mail: ['M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z', 'M22 6l-10 7L2 6'],
  send: ['M22 2 11 13', 'M22 2l-7 20-4-9-9-4 20-7z'],
  radar: [CIRCLE, 'M16 12a4 4 0 1 1-4-4', 'M12 12l6.5-6.5'],
  pause: ['M8 5v14', 'M16 5v14'],
  menu: ['M4 6h16', 'M4 12h16', 'M4 18h16'],
  x: ['M18 6 6 18', 'M6 6l12 12'],
  plus: ['M12 5v14', 'M5 12h14'],
  /** Willay's provisional logo: a watching eye. */
  eye: ['M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z', 'M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z'],
  home: ['M3 10.5 12 3l9 7.5', 'M5 9.5V21h14V9.5', 'M10 21v-6h4v6'],
  map: ['M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z', 'M9 4v14', 'M15 6v14'],
  antenna: ['M12 12v9', 'M9 21h6', ...WAVES],
  logout: ['M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4', 'M16 17l5-5-5-5', 'M21 12H9'],
} as const satisfies Record<string, readonly string[]>;

export type IconName = keyof typeof ICONS;

/** The same icon as markup, for HTML built outside Angular (Leaflet markers). */
export function iconSvg(name: IconName, size: number): string {
  const paths = ICONS[name].map((d) => `<path d="${d}"/>`).join('');
  return (
    `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" ` +
    `stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ` +
    `focusable="false">${paths}</svg>`
  );
}

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
