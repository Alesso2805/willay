import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslationKey, t } from '../i18n/i18n';
import { Icon, IconName } from '../ui/icon';
import { THEME_CHOICES, ThemeChoice, ThemeService } from './theme';

const LOOKS: Readonly<Record<ThemeChoice, { icon: IconName; label: TranslationKey }>> = {
  system: { icon: 'monitor', label: 'app.themes.system' },
  light: { icon: 'sun', label: 'app.themes.light' },
  dark: { icon: 'moon', label: 'app.themes.dark' },
};

/**
 * System / Light / Dark switch (VIG-41), drawn on night blue: the navigation and the sign-in
 * screen. Each option says its name next to its icon: a sun or a moon alone is easy to misread.
 */
@Component({
  selector: 'app-theme-picker',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Icon],
  template: `
    <div
      role="group"
      [attr.aria-label]="t('app.theme')"
      class="inline-flex rounded-lg p-0.5 ring-1 ring-night-700"
    >
      @for (choice of choices; track choice) {
        <button
          type="button"
          class="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold"
          [class]="
            choice === service.choice()
              ? 'bg-night-700 text-white'
              : 'text-night-300 hover:text-white'
          "
          [attr.aria-pressed]="choice === service.choice()"
          (click)="service.choose(choice)"
        >
          <app-icon [name]="looks[choice].icon" [size]="14" />
          {{ t(looks[choice].label) }}
        </button>
      }
    </div>
  `,
})
export class ThemePicker {
  protected readonly service = inject(ThemeService);
  protected readonly choices = THEME_CHOICES;
  protected readonly looks = LOOKS;
  protected readonly t = t;
}
