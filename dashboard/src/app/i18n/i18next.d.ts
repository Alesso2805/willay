import 'i18next';
import type es from '../../i18n/es.json';

// Types every key from the Spanish file: a key missing from it is a compile error.
declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'translation';
    resources: { translation: typeof es };
  }
}
