import { Injectable, computed, effect, signal } from '@angular/core';

export type ThemeChoice = 'system' | 'light' | 'dark';
export type Theme = 'light' | 'dark';

export const THEME_CHOICES: readonly ThemeChoice[] = ['system', 'light', 'dark'];

/** Read by the script in index.html too, which applies the theme before the app loads. */
export const THEME_STORAGE_KEY = 'willay.theme';
const DARK_QUERY = '(prefers-color-scheme: dark)';

/**
 * Light or dark mode. It follows the system unless the user picks one, a choice kept in
 * this browser rather than in the database: a phone may go dark at night while the office screen
 * stays light, and the theme must apply before the app loads, when there is no user to ask the
 * API about yet.
 *
 * Applying a theme only toggles the `dark` class on <html>: every color is a CSS variable, so
 * nothing redraws, and a half-written form survives the system turning dark at sunset.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly media = typeof matchMedia === 'function' ? matchMedia(DARK_QUERY) : null;
  private readonly systemDark = signal(this.media?.matches ?? false);
  private readonly _choice = signal<ThemeChoice>(storedChoice());

  /** What the user picked; `system` until they pick. */
  readonly choice = this._choice.asReadonly();
  /** The theme on screen. */
  readonly theme = computed<Theme>(() => {
    const choice = this._choice();
    if (choice !== 'system') return choice;
    return this.systemDark() ? 'dark' : 'light';
  });

  constructor() {
    this.media?.addEventListener('change', (event) => this.systemDark.set(event.matches));
    effect(() => applyTheme(this.theme()));
  }

  choose(choice: ThemeChoice): void {
    this._choice.set(choice);
    try {
      if (choice === 'system') localStorage.removeItem(THEME_STORAGE_KEY);
      else localStorage.setItem(THEME_STORAGE_KEY, choice);
    } catch {
      // Storage blocked (private mode, a policy): the choice lasts until the tab closes.
    }
  }
}

export function applyTheme(theme: Theme, root: HTMLElement = document.documentElement): void {
  root.classList.toggle('dark', theme === 'dark');
}

function storedChoice(): ThemeChoice {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return stored === 'light' || stored === 'dark' ? stored : 'system';
  } catch {
    return 'system';
  }
}
