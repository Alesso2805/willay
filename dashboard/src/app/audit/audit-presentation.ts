import { causeLabel } from '../incidents/incident-presentation';
import { VARIABLES, variableLabel } from '../stations/station-presentation';
import { Variable } from '../stations/stations.api';
import { TranslationKey, t } from '../i18n/i18n';
import { localTime } from '../ui/formats';
import { RISK_LEVEL_STATES, SEVERITIES, VisualState } from '../ui/visual-states';
import { AuditEntry, EntityType } from './audit.api';

/** Stored values that are codes, in the words the rest of the dashboard uses for them. */
const VALUE_LABELS: Readonly<Record<string, (value: string) => string | undefined>> = {
  type: causeLabel,
  severity: (v) => stateLabel(SEVERITIES[v as keyof typeof SEVERITIES]),
  risk_level: (v) => stateLabel(RISK_LEVEL_STATES[v as keyof typeof RISK_LEVEL_STATES]),
  variable: (v) => (VARIABLES.includes(v as Variable) ? variableLabel(v as Variable) : undefined),
  status: (v) => (v === 'active' || v === 'inactive' ? t(`audit.values.${v}`) : undefined),
  source: (v) => (v === 'sensor' || v === 'simulator' ? t(`audit.values.${v}`) : undefined),
};

function stateLabel(state: VisualState | undefined): string | undefined {
  return state ? t(state.labelKey) : undefined;
}

export const ENTITY_TYPES: readonly EntityType[] = [
  'risk_zone',
  'station',
  'rule',
  'escalation_policy',
  'contact',
  'contact_group',
];

/** "Zona", "Station"… for the filter. */
export function entityLabel(type: EntityType): string {
  return t(`audit.entities.${type}`);
}

const ACTION_KEYS: Readonly<Record<string, TranslationKey>> = {
  create: 'audit.actions.create',
  update: 'audit.actions.update',
  delete: 'audit.actions.delete',
  deactivate: 'audit.actions.deactivate',
  rotate_api_key: 'audit.actions.rotate_api_key',
  readings_reprocessed: 'audit.actions.readings_reprocessed',
  removed_from_groups: 'audit.actions.removed_from_groups',
  telegram_link_created: 'audit.actions.telegram_link_created',
  telegram_linked: 'audit.actions.telegram_linked',
  telegram_unlinked: 'audit.actions.telegram_unlinked',
};

const FIELD_KEYS: Readonly<Record<string, TranslationKey>> = {
  name: 'audit.fields.name',
  full_name: 'audit.fields.full_name',
  code: 'audit.fields.code',
  description: 'audit.fields.description',
  risk_level: 'audit.fields.risk_level',
  population_estimate: 'audit.fields.population_estimate',
  is_active: 'audit.fields.is_active',
  geometry: 'audit.fields.geometry',
  variable: 'audit.fields.variable',
  unit: 'audit.fields.unit',
  location: 'audit.fields.location',
  source: 'audit.fields.source',
  expected_interval_s: 'audit.fields.expected_interval_s',
  silence_multiplier: 'audit.fields.silence_multiplier',
  status: 'audit.fields.status',
  zones: 'audit.fields.zones',
  api_key_rotated_at: 'audit.fields.api_key_rotated_at',
  telegram_link_expires_at: 'audit.fields.telegram_link_expires_at',
  email: 'audit.fields.email',
  telegram_linked: 'audit.fields.telegram_linked',
  groups: 'audit.fields.groups',
  members: 'audit.fields.members',
  zone: 'audit.fields.zone',
  type: 'audit.fields.type',
  station: 'audit.fields.station',
  params: 'audit.fields.params',
  severity: 'audit.fields.severity',
  escalation_policy: 'audit.fields.escalation_policy',
  cooldown_s: 'audit.fields.cooldown_s',
  levels: 'audit.fields.levels',
  readings: 'audit.fields.readings',
};

export interface FieldChange {
  field: string;
  before: string;
  after: string;
}

/** "Creó la regla Chosica · RIM-CHO-02"; who did it is in `actorLabel`. */
export function actionText(entry: AuditEntry): string {
  const type = entry.entity_type as EntityType;
  const entity = ENTITY_TYPES.includes(type) ? t(`audit.entityPhrases.${type}`) : entry.entity_type;
  const name = entityName(entry);
  const key = ACTION_KEYS[entry.action];
  // A whole sentence per action: word order differs between languages.
  const text = key ? t(key, { entity, name }) : `${entry.action} ${entity} ${name}`;
  // Spanish contracts "de el" and "a el": "del contacto", "al contacto". No-op in English.
  return text.replace(/\bde el\b/, 'del').replace(/\ba el\b/, 'al');
}

/** Who did it. Without an author, only the contact can have done it, from Telegram (SPEC). */
export function actorLabel(entry: AuditEntry): string {
  if (entry.actor) return entry.actor.name;
  return t(entry.entity_type === 'contact' ? 'audit.theContact' : 'audit.system');
}

/** A readable name for the entity as it was then, from its own snapshot. */
export function entityName(entry: AuditEntry): string {
  const snapshot = entry.after ?? entry.before ?? {};
  if (entry.entity_type === 'rule') {
    const station =
      typeof snapshot['station'] === 'string' ? snapshot['station'] : t('audit.wholeZone');
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
          ? { field: fieldLabel(key), before: t('audit.oldPolygon'), after: t('audit.newPolygon') }
          : {
              field: fieldLabel(key),
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
  if (key === 'geometry') return t('audit.polygon'); // its coordinates say nothing at a glance
  if (typeof value === 'boolean') return t(value ? 'audit.yes' : 'audit.no');
  if (typeof value === 'string' && VALUE_LABELS[key]) return VALUE_LABELS[key](value) ?? value;
  if (typeof value === 'string' && INSTANT.test(value)) return localTime(value, timezone);
  if (Array.isArray(value)) {
    if (value.length === 0) return t('audit.none');
    return value
      .map((item) => (typeof item === 'object' ? compact(item, timezone) : String(item)))
      .join(', ');
  }
  if (typeof value === 'object') return compact(value, timezone);
  return String(value);
}

/** Keys and codes inside nested values, mostly a rule's params. */
const NESTED_KEYS: Readonly<Record<string, TranslationKey>> = {
  operator: 'audit.nested.operator',
  value: 'audit.nested.value',
  consecutive: 'audit.nested.consecutive',
  direction: 'audit.nested.direction',
  delta: 'audit.nested.delta',
  window_minutes: 'audit.nested.window_minutes',
  zone_id: 'audit.nested.zone_id',
  position: 'audit.nested.position',
  measured_at: 'audit.nested.measured_at',
  attempts: 'audit.nested.attempts',
  last_error: 'audit.nested.last_error',
};
const NESTED_VALUE_KEYS: Readonly<Record<string, TranslationKey>> = {
  gt: 'audit.nestedValues.gt',
  ge: 'audit.nestedValues.ge',
  lt: 'audit.nestedValues.lt',
  le: 'audit.nestedValues.le',
  down: 'audit.nestedValues.down',
  up: 'audit.nestedValues.up',
  upstream: 'audit.nestedValues.upstream',
  in_zone: 'audit.nestedValues.in_zone',
  downstream: 'audit.nestedValues.downstream',
};

function fieldLabel(key: string): string {
  return FIELD_KEYS[key] ? t(FIELD_KEYS[key]) : key;
}

function compact(value: unknown, timezone: string): string {
  if (value === null || typeof value !== 'object') return String(value);
  return Object.entries(value as Record<string, unknown>)
    .map(([k, v]) => {
      const text = typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v);
      const shown = INSTANT.test(text)
        ? localTime(text, timezone, true)
        : NESTED_VALUE_KEYS[text]
          ? t(NESTED_VALUE_KEYS[text])
          : text;
      return `${NESTED_KEYS[k] ? t(NESTED_KEYS[k]) : k}: ${shown}`;
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
