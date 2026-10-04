import i18next, { ParseKeys } from 'i18next';

/**
 * Willay's languages and the translator every visible text goes through (VIG-40, ADR-0008).
 *
 * The texts live in one JSON file per language (src/i18n), in i18next's format, which the
 * translation platforms read. Keys are typed from es.json: a key that does not exist does not
 * compile. The translator does not depend on Angular, so the pure presentation functions use it
 * as they are and their specs need no TestBed.
 *
 * Changing the language re-renders the whole app (see App), so a text is always translated when
 * it is drawn and nothing has to react to the change on its own.
 */
export const LANGUAGES = ['es', 'en'] as const;
export type Language = (typeof LANGUAGES)[number];
export const DEFAULT_LANGUAGE: Language = 'es';

/** Each language in itself: whoever cannot read the current language still finds theirs. */
export const LANGUAGE_NAMES: Readonly<Record<Language, string>> = { es: 'Español', en: 'English' };

/** Dates and numbers the way each language's readers expect them (Spanish: as in Peru). */
const LOCALES: Readonly<Record<Language, string>> = { es: 'es-PE', en: 'en-US' };

export type TranslationKey = ParseKeys;
export type TranslationOptions = Record<string, unknown> & { count?: number };

// Each language is its own chunk, downloaded only by whoever uses it: adding languages, or
// texts, does not grow what everyone downloads. The app waits for it before its first render.
// Untyped on purpose: languages differ in their plural forms; translations.spec checks them.
const LOADERS: Readonly<Record<Language, () => Promise<object>>> = {
  es: () => import('../../i18n/es.json').then((module) => module.default),
  en: () => import('../../i18n/en.json').then((module) => module.default),
};

const i18n = i18next.createInstance();
let initialized: Promise<unknown> | null = null;

function init(): Promise<unknown> {
  initialized ??= i18n.init({
    // No fallback language: a spec checks that every language has every text.
    fallbackLng: false,
    supportedLngs: [...LANGUAGES],
    resources: {},
    // Angular escapes interpolated text; pages that build HTML strings escape it themselves.
    interpolation: { escapeValue: false },
  });
  return initialized;
}

/** Loads the language if needed and makes it the current one. */
export async function useLanguage(language: Language): Promise<void> {
  await init();
  if (!i18n.hasResourceBundle(language, 'translation')) {
    i18n.addResourceBundle(language, 'translation', await LOADERS[language]());
  }
  await i18n.changeLanguage(language);
}

/** The text of a key in the current language. Plurals take `count`. */
export function t(key: TranslationKey, options?: TranslationOptions): string {
  return i18n.t(key, options ?? {}) as string;
}

export function currentLanguage(): Language {
  return isLanguage(i18n.language) ? i18n.language : DEFAULT_LANGUAGE;
}

/** The Intl locale for dates and numbers in the current language. */
export function currentLocale(): string {
  return LOCALES[currentLanguage()];
}

export function isLanguage(value: unknown): value is Language {
  return typeof value === 'string' && (LANGUAGES as readonly string[]).includes(value);
}

/** The first of the browser's languages that Willay speaks: "en-GB" counts as English. */
export function browserLanguage(preferred: readonly string[]): Language | null {
  for (const tag of preferred) {
    const base = tag.toLowerCase().split('-')[0];
    if (isLanguage(base)) return base;
  }
  return null;
}

/** Tests only: report every key that has no text instead of showing the key on screen. */
export function reportMissingKeys(report: (language: string, key: string) => void): void {
  i18n.options.saveMissing = true;
  i18n.options.missingKeyHandler = (languages, _namespace, key) => report(languages.join(','), key);
}
