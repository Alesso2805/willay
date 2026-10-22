import { currentLocale } from '../i18n/i18n';

/**
 * Shared dashboard formats, in the current language. Times use the
 * organization's time zone, not the browser's: a travelling operator sees the same times as the
 * emails and Telegram messages.
 */

const cache = new Map<string, Intl.RelativeTimeFormat | Intl.DateTimeFormat | Intl.NumberFormat>();

// Building an Intl formatter is costly and ages are redrawn every second: one per locale and use.
function cached<T extends Intl.RelativeTimeFormat | Intl.DateTimeFormat | Intl.NumberFormat>(
  id: string,
  build: (locale: string) => T,
): T {
  const locale = currentLocale();
  const key = `${locale}|${id}`;
  let formatter = cache.get(key) as T | undefined;
  if (formatter === undefined) {
    formatter = build(locale);
    cache.set(key, formatter);
  }
  return formatter;
}

/** "hace 12 s", "hace 3 min" ("12s ago", "3m ago")... from an ISO date. */
export function ageText(iso: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  const relative = cached(
    'age',
    (locale) => new Intl.RelativeTimeFormat(locale, { style: 'narrow', numeric: 'always' }),
  );
  if (seconds < 60) return relative.format(-seconds, 'second');
  if (seconds < 3600) return relative.format(-Math.floor(seconds / 60), 'minute');
  if (seconds < 86_400) return relative.format(-Math.floor(seconds / 3600), 'hour');
  return relative.format(-Math.floor(seconds / 86_400), 'day');
}

/**
 * "30/09/2026 18:57", as in the emails and on Telegram; in English, "Sep 30, 2026, 18:57", whose
 * month name avoids reading 04/10 as April 10. With `seconds`, the seconds too: a timeline has
 * several events within the same minute. Always a 24-hour clock.
 */
export function localTime(iso: string, timezone: string, seconds = false): string {
  const format = cached(
    `time|${timezone}|${seconds}`,
    (locale) =>
      new Intl.DateTimeFormat(locale, {
        timeZone: timezone,
        day: locale.startsWith('es') ? '2-digit' : 'numeric',
        month: locale.startsWith('es') ? '2-digit' : 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: seconds ? '2-digit' : undefined,
        hourCycle: 'h23',
      }),
  );
  if (!currentLocale().startsWith('es')) return format.format(new Date(iso));
  // Spanish: day/month/year and a space, exactly as the alert messages write it.
  const parts = format.formatToParts(new Date(iso));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? '';
  const time = `${part('day')}/${part('month')}/${part('year')} ${part('hour')}:${part('minute')}`;
  return seconds ? `${time}:${part('second')}` : time;
}

/** Whole quantities, readable at a glance, such as a population: 45,000. */
export function wholeNumber(value: number): string {
  return cached(
    'count',
    (locale) => new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }),
  ).format(value);
}

const NUMBER = new Intl.NumberFormat('en-US', { maximumSignificantDigits: 6, useGrouping: false });

/**
 * "83.234": decimal point (as in Peru, and in English) and up to 6 significant digits, the same
 * number the email and Telegram show (Python's `:g` format).
 */
export function measurement(value: number): string {
  return NUMBER.format(value);
}

/** "83.234 m3/s". */
export function valueWithUnit(value: number, unit: string): string {
  return `${measurement(value)} ${unit}`;
}
