// Every spec starts in Spanish, the default language, and fails on a key that has no text.
import { reportMissingKeys, useLanguage } from './app/i18n/i18n';

await useLanguage('es');
const missing: string[] = [];
reportMissingKeys((language, key) => missing.push(`${language}: ${key}`));

afterEach(async () => {
  // A spec that switched to English leaves the next one in Spanish.
  await useLanguage('es');
  if (missing.length > 0) throw new Error(`Keys without text: ${missing.splice(0).join(', ')}`);
});
