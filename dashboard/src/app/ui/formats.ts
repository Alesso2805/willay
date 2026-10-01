/**
 * Shared dashboard formats (VIG-33). Times use the organization's time zone, not the
 * browser's: a travelling operator sees the same times as the emails and Telegram messages.
 */

/** "hace 12 s", "hace 3 min"... from an ISO date. */
export function ageText(iso: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (seconds < 60) return `hace ${seconds} s`;
  if (seconds < 3600) return `hace ${Math.floor(seconds / 60)} min`;
  if (seconds < 86_400) return `hace ${Math.floor(seconds / 3600)} h`;
  return `hace ${Math.floor(seconds / 86_400)} d`;
}

/** "30/09/2026 18:57", as in the emails and on Telegram. */
export function localTime(iso: string, timezone: string): string {
  const parts = new Intl.DateTimeFormat('es-PE', {
    timeZone: timezone,
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(iso));
  const part = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? '';
  return `${part('day')}/${part('month')}/${part('year')} ${part('hour')}:${part('minute')}`;
}

const COUNT = new Intl.NumberFormat('es-PE', { maximumFractionDigits: 0 });

/** Whole quantities, readable at a glance, such as a population: 45,000. */
export function wholeNumber(value: number): string {
  return COUNT.format(value);
}

const NUMBER = new Intl.NumberFormat('en-US', { maximumSignificantDigits: 6, useGrouping: false });

/**
 * "83.234": decimal point (as in Peru) and up to 6 significant digits, the same number the
 * email and Telegram show (Python's `:g` format).
 */
export function measurement(value: number): string {
  return NUMBER.format(value);
}

/** "83.234 m3/s". */
export function valueWithUnit(value: number, unit: string): string {
  return `${measurement(value)} ${unit}`;
}
