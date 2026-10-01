/**
 * Formatos comunes del panel (VIG-33). Las horas van en la zona horaria de la organización,
 * no en la del navegador: un operador de viaje ve las mismas horas que los correos y los
 * mensajes de Telegram.
 */

/** "hace 12 s", "hace 3 min"... a partir de una fecha ISO. */
export function ageText(iso: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (seconds < 60) return `hace ${seconds} s`;
  if (seconds < 3600) return `hace ${Math.floor(seconds / 60)} min`;
  if (seconds < 86_400) return `hace ${Math.floor(seconds / 3600)} h`;
  return `hace ${Math.floor(seconds / 86_400)} d`;
}

/** "30/09/2026 18:57", como en los correos y en Telegram. */
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

const NUMBER = new Intl.NumberFormat('en-US', { maximumSignificantDigits: 6, useGrouping: false });

/**
 * "83.234 m3/s": punto decimal (como en Perú) y hasta 6 cifras significativas, el mismo
 * número que muestran el correo y Telegram (formato `:g` de Python).
 */
export function valueWithUnit(value: number, unit: string): string {
  return `${NUMBER.format(value)} ${unit}`;
}
