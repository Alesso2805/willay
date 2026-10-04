import { causeLabel } from '../incidents/incident-presentation';
import { VARIABLES, variableLabel } from '../stations/station-presentation';
import { Variable } from '../stations/stations.api';
import { t } from '../i18n/i18n';
import { localTime } from '../ui/formats';
import { RISK_LEVEL_STATES, SEVERITIES, VisualState } from '../ui/visual-states';
import { AuditEntry, EntityType } from './audit.api';

/** Stored values that are codes, in the words the rest of the dashboard uses for them. */
const VALUE_LABELS: Readonly<Record<string, (value: string) => string | undefined>> = {
  type: causeLabel,
  severity: (v) => stateLabel(SEVERITIES[v as keyof typeof SEVERITIES]),
  risk_level: (v) => stateLabel(RISK_LEVEL_STATES[v as keyof typeof RISK_LEVEL_STATES]),
  variable: (v) => (VARIABLES.includes(v as Variable) ? variableLabel(v as Variable) : undefined),
  status: (v) => ({ active: 'Activa', inactive: 'Inactiva' })[v],
  source: (v) => ({ sensor: 'Sensor', simulator: 'Simulador' })[v],
};

function stateLabel(state: VisualState | undefined): string | undefined {
  return state ? t(state.labelKey) : undefined;
}

export const ENTITY_LABELS: Readonly<Record<EntityType, string>> = {
  risk_zone: 'Zona',
  station: 'Estación',
  rule: 'Regla',
  escalation_policy: 'Política',
  contact: 'Contacto',
  contact_group: 'Grupo',
};

const ACTION_LABELS: Readonly<Record<string, string>> = {
  create: 'Creó',
  update: 'Editó',
  delete: 'Eliminó',
  deactivate: 'Desactivó',
  rotate_api_key: 'Rotó la API key de',
  readings_reprocessed: 'Reprocesó lecturas de',
  removed_from_groups: 'Quitó de sus grupos a',
  telegram_link_created: 'Generó el enlace de Telegram de',
  telegram_linked: 'Vinculó su Telegram',
  telegram_unlinked: 'Desvinculó el Telegram de',
};

const FIELD_LABELS: Readonly<Record<string, string>> = {
  name: 'Nombre',
  full_name: 'Nombre',
  code: 'Código',
  description: 'Descripción',
  risk_level: 'Nivel de riesgo',
  population_estimate: 'Población estimada',
  is_active: 'Activa',
  geometry: 'Polígono',
  variable: 'Variable',
  unit: 'Unidad',
  location: 'Ubicación',
  source: 'Origen',
  expected_interval_s: 'Intervalo esperado (s)',
  silence_multiplier: 'Silencio tras (× intervalo)',
  status: 'Estado',
  zones: 'Zonas',
  api_key_rotated_at: 'Clave rotada',
  telegram_link_expires_at: 'Enlace de Telegram válido hasta',
  email: 'Correo',
  telegram_linked: 'Telegram vinculado',
  groups: 'Grupos',
  members: 'Miembros',
  zone: 'Zona',
  type: 'Tipo',
  station: 'Estación',
  params: 'Parámetros',
  severity: 'Severidad',
  escalation_policy: 'Política',
  cooldown_s: 'Espera tras resolver (s)',
  levels: 'Niveles',
  readings: 'Lecturas',
};

export interface FieldChange {
  field: string;
  before: string;
  after: string;
}

/** With its article, to build sentences: "Creó la regla …", "Editó el contacto …". */
const ENTITY_PHRASES: Readonly<Record<EntityType, string>> = {
  risk_zone: 'la zona',
  station: 'la estación',
  rule: 'la regla',
  escalation_policy: 'la política',
  contact: 'el contacto',
  contact_group: 'el grupo',
};

/** "Creó la regla Chosica · RIM-CHO-02"; who did it is in `actorLabel`. */
export function actionText(entry: AuditEntry): string {
  const verb = ACTION_LABELS[entry.action] ?? entry.action;
  if (entry.action === 'telegram_linked') return `${verb}: ${entityName(entry)}`;
  const entity = ENTITY_PHRASES[entry.entity_type as EntityType] ?? entry.entity_type;
  // Spanish contracts "de el" and "a el": "del contacto", "al contacto".
  return `${verb} ${entity} ${entityName(entry)}`
    .replace(/\bde el\b/, 'del')
    .replace(/\ba el\b/, 'al');
}

/** Who did it. Without an author, only the contact can have done it, from Telegram (SPEC). */
export function actorLabel(entry: AuditEntry): string {
  if (entry.actor) return entry.actor.name;
  return entry.entity_type === 'contact' ? 'El propio contacto' : 'Sistema';
}

/** A readable name for the entity as it was then, from its own snapshot. */
export function entityName(entry: AuditEntry): string {
  const snapshot = entry.after ?? entry.before ?? {};
  if (entry.entity_type === 'rule') {
    const station = typeof snapshot['station'] === 'string' ? snapshot['station'] : 'toda la zona';
    return `${String(snapshot['zone'] ?? '')} · ${station}`;
  }
  for (const key of ['code', 'name', 'full_name']) {
    if (typeof snapshot[key] === 'string') return snapshot[key];
  }
  // A snapshot without a name (a Telegram link records only its expiry): its current name.
  return entry.entity_name ?? entry.entity_id.slice(0, 8);
}

/** Only the fields that changed; on creation, what it was created with; on deletion, what it had. */
export function fieldChanges(entry: AuditEntry, timezone = 'UTC'): FieldChange[] {
  const valueText = (key: string, value: unknown) => readable(key, value, timezone);
  const before = entry.before ?? {};
  const after = entry.after ?? {};
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];
  return (
    keys
      .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
      .map((key) =>
        // An edited polygon reads the same either way: say which one is which.
        key === 'geometry' && before[key] && after[key]
          ? { field: FIELD_LABELS[key], before: 'polígono anterior', after: 'polígono nuevo' }
          : {
              field: FIELD_LABELS[key] ?? key,
              before: key in before ? valueText(key, before[key]) : '—',
              after: key in after ? valueText(key, after[key]) : '—',
            },
      )
      // Empty on both sides (a null field on creation) is not a change worth reading.
      .filter((change) => change.before !== '—' || change.after !== '—')
  );
}

/** An instant stored as ISO text ("2026-10-09T18:17:56.28+00:00"): shown in local time. */
const INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

function readable(key: string, value: unknown, timezone: string): string {
  if (value === null || value === undefined || value === '') return '—';
  if (key === 'geometry') return 'polígono'; // its coordinates say nothing at a glance
  if (typeof value === 'boolean') return value ? 'Sí' : 'No';
  if (typeof value === 'string' && VALUE_LABELS[key]) return VALUE_LABELS[key](value) ?? value;
  if (typeof value === 'string' && INSTANT.test(value)) return localTime(value, timezone);
  if (Array.isArray(value)) {
    if (value.length === 0) return 'ninguno';
    return value
      .map((item) => (typeof item === 'object' ? compact(item, timezone) : String(item)))
      .join(', ');
  }
  if (typeof value === 'object') return compact(value, timezone);
  return String(value);
}

/** Keys and codes inside nested values, mostly a rule's params. */
const NESTED_LABELS: Readonly<Record<string, string>> = {
  operator: 'condición',
  value: 'límite',
  consecutive: 'lecturas seguidas',
  direction: 'dirección',
  delta: 'cambio',
  window_minutes: 'ventana (min)',
  zone_id: 'zona',
  position: 'posición',
  measured_at: 'medición',
  attempts: 'intentos',
  last_error: 'último error',
};
const NESTED_VALUES: Readonly<Record<string, string>> = {
  gt: 'mayor que',
  ge: 'mayor o igual que',
  lt: 'menor que',
  le: 'menor o igual que',
  down: 'baja',
  up: 'sube',
  upstream: 'aguas arriba',
  in_zone: 'en la zona',
  downstream: 'aguas abajo',
};

function compact(value: unknown, timezone: string): string {
  if (value === null || typeof value !== 'object') return String(value);
  return Object.entries(value as Record<string, unknown>)
    .map(([k, v]) => {
      const text = typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v);
      const shown = INSTANT.test(text)
        ? localTime(text, timezone, true)
        : (NESTED_VALUES[text] ?? text);
      return `${NESTED_LABELS[k] ?? k}: ${shown}`;
    })
    .join(', ');
}

/**
 * The instant a calendar day starts in a time zone, as ISO: the date filters are the
 * organization's days, not the browser's.
 */
export function dayStart(day: string, timeZone: string): string {
  const [year, month, date] = day.split('-').map(Number);
  const guess = Date.UTC(year, month - 1, date);
  // Twice: the offset at the first guess may differ from the one at the result (DST changes).
  const first = guess - offsetMs(guess, timeZone);
  return new Date(guess - offsetMs(first, timeZone)).toISOString();
}

/** The day after, for an inclusive "until" day sent as an exclusive instant. */
export function nextDay(day: string): string {
  const [year, month, date] = day.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, date + 1)).toISOString().slice(0, 10);
}

function offsetMs(instant: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(new Date(instant));
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  const wall = Date.UTC(
    get('year'),
    get('month') - 1,
    get('day'),
    get('hour'),
    get('minute'),
    get('second'),
  );
  return wall - instant;
}
