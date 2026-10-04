import en from '../../i18n/en.json';
import es from '../../i18n/es.json';
import { LANGUAGES, Language } from './i18n';

/**
 * SPEC (VIG-40): a test fails if a key is missing in either language. The keys of the code are
 * typed from es.json, so here every other file is held to Spanish.
 */
const FILES: Readonly<Record<Language, object>> = { es, en };
const PLURAL = /_(zero|one|two|few|many|other)$/;
const PLACEHOLDER = /\{\{\s*(\w+)\s*\}\}/g;

function texts(node: object, prefix = ''): [string, string][] {
  return Object.entries(node).flatMap(([key, value]): [string, string][] =>
    typeof value === 'string'
      ? [[`${prefix}${key}`, value]]
      : texts(value as object, `${prefix}${key}.`),
  );
}

/** Key without its plural form ("x_one" -> "x") -> every text it has in that language. */
function byBaseKey(language: Language): Map<string, string[]> {
  const result = new Map<string, string[]>();
  for (const [key, text] of texts(FILES[language])) {
    const base = key.replace(PLURAL, '');
    result.set(base, [...(result.get(base) ?? []), text]);
  }
  return result;
}

function placeholders(values: readonly string[]): string[] {
  return [...new Set(values.flatMap((v) => [...v.matchAll(PLACEHOLDER)].map((m) => m[1])))].sort();
}

describe('translation files', () => {
  it('there is one per language', () => {
    expect(Object.keys(FILES).sort()).toEqual([...LANGUAGES].sort());
  });

  it.each(LANGUAGES)('%s has exactly the texts Spanish has', (language) => {
    expect([...byBaseKey(language).keys()].sort()).toEqual([...byBaseKey('es').keys()].sort());
  });

  it.each(LANGUAGES)('%s has every plural form its grammar needs', (language) => {
    // Spanish needs "many" too (1,000,000 → "1 millón de…"): without it i18next shows the key.
    const forms = new Intl.PluralRules(language).resolvedOptions().pluralCategories;
    const keys = new Set(texts(FILES[language]).map(([key]) => key));
    const plurals = new Set(
      [...keys].filter((k) => PLURAL.test(k)).map((k) => k.replace(PLURAL, '')),
    );
    for (const plural of plurals) {
      for (const form of forms)
        expect(keys.has(`${plural}_${form}`), `${plural}_${form}`).toBe(true);
    }
  });

  it.each(LANGUAGES)('%s keeps the placeholders of every Spanish text', (language) => {
    const spanish = byBaseKey('es');
    for (const [key, values] of byBaseKey(language)) {
      expect(placeholders(values), key).toEqual(placeholders(spanish.get(key) ?? []));
    }
  });

  it.each(LANGUAGES)('%s has no empty text', (language) => {
    for (const [key, text] of texts(FILES[language])) expect(text.trim(), key).not.toBe('');
  });
});
