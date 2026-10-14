import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { LANGUAGES, LANGUAGE_NAMES, Language, t } from './i18n';
import { LanguageService } from './language';

/**
 * ES / EN switch (VIG-40). Each option is written in its own language and marked with `lang`,
 * so a screen reader pronounces it right and whoever cannot read the current language still
 * recognizes theirs.
 */
@Component({
  selector: 'app-language-picker',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      role="group"
      [attr.aria-label]="t('app.language')"
      class="inline-flex rounded-lg p-0.5 ring-1"
      [class]="frame()"
    >
      @for (language of languages; track language) {
        <button
          type="button"
          class="rounded-md px-2.5 py-1 text-xs font-semibold uppercase"
          [class]="language === service.current() ? selected() : idle()"
          [attr.lang]="language"
          [attr.aria-label]="names[language]"
          [attr.aria-pressed]="language === service.current()"
          (click)="choose(language)"
        >
          {{ language }}
        </button>
      }
    </div>
  `,
})
export class LanguagePicker {
  /** Signed in: the choice is saved for the user, not only in this browser. */
  readonly signedIn = input(false);
  /** `dark` on night blue (the sidebar and the sign-in screen); `light` on a page's surface. */
  readonly tone = input<'dark' | 'light'>('dark');

  protected readonly service = inject(LanguageService);
  protected readonly languages = LANGUAGES;
  protected readonly names = LANGUAGE_NAMES;
  protected readonly t = t;

  protected frame(): string {
    return this.tone() === 'dark' ? 'ring-night-700' : 'ring-line-strong';
  }

  protected selected(): string {
    return this.tone() === 'dark' ? 'bg-night-700 text-white' : 'bg-brand-600 text-white';
  }

  protected idle(): string {
    return this.tone() === 'dark'
      ? 'text-night-300 hover:text-white'
      : 'text-ink-muted hover:text-ink';
  }

  protected choose(language: Language): void {
    void this.service.choose(language, this.signedIn());
  }
}
