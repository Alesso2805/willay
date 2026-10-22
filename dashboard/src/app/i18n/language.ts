import { HttpClient, HttpInterceptorFn } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { settings } from '../settings';
import {
  DEFAULT_LANGUAGE,
  Language,
  browserLanguage,
  currentLanguage,
  isLanguage,
  useLanguage,
} from './i18n';

// This browser's last language, so the sign-in screen already shows it.
const STORED = 'willay.language';
// A language picked on the sign-in screen, before the Keycloak redirect: saved once signed in.
const PENDING = 'willay.language.pending';

/**
 * Which language the dashboard shows. The user's choice is saved in the database, so it
 * follows them to any device; until they choose, the browser's language, and else Spanish.
 */
@Injectable({ providedIn: 'root' })
export class LanguageService {
  private readonly http = inject(HttpClient);
  private readonly _current = signal<Language>(DEFAULT_LANGUAGE);
  /** The language on screen. When it changes, the app re-renders in it (see App). */
  readonly current = this._current.asReadonly();

  /** Before the first render: this browser's last language, else its own, else Spanish. */
  start(): Promise<void> {
    const stored = read(localStorage, STORED);
    const initial = isLanguage(stored) ? stored : browserLanguage(navigator.languages);
    return this.use(initial ?? DEFAULT_LANGUAGE);
  }

  /** Signed in, with the language saved for the user (null: never chose one). */
  async adopt(saved: Language | null): Promise<void> {
    if (read(sessionStorage, PENDING) !== null) {
      // Just picked on the sign-in screen: a fresher choice than the saved one.
      write(sessionStorage, PENDING, null);
      this.save(this._current());
    } else if (saved !== null && saved !== this._current()) {
      await this.use(saved);
    }
  }

  /**
   * The user picks a language: shown at once and, if signed in, saved for them. Pressing the one
   * already on screen counts too: it may only be there because it is the browser's.
   */
  async choose(language: Language, signedIn: boolean): Promise<void> {
    if (language !== this._current()) await this.use(language);
    if (signedIn) this.save(language);
    else write(sessionStorage, PENDING, language);
  }

  private async use(language: Language): Promise<void> {
    await useLanguage(language);
    document.documentElement.lang = language;
    write(localStorage, STORED, language);
    this._current.set(language);
  }

  private save(language: Language): void {
    // A preference: if saving fails, the language still applies here and in this browser.
    this.http.put(`${settings.apiUrl}/v1/me/language`, { language }).subscribe({
      error: (error: unknown) => console.warn('The language could not be saved', error),
    });
  }
}

/** API errors come back in the language on screen (Accept-Language). */
export const acceptLanguageInterceptor: HttpInterceptorFn = (request, next) =>
  request.url.startsWith(settings.apiUrl)
    ? next(request.clone({ setHeaders: { 'Accept-Language': currentLanguage() } }))
    : next(request);

// Storage may be unavailable (private mode, blocked site data): the language is only a
// convenience there, so failures are ignored.
function read(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

function write(storage: Storage, key: string, value: string | null): void {
  try {
    if (value === null) storage.removeItem(key);
    else storage.setItem(key, value);
  } catch {
    // ignored: see read()
  }
}
