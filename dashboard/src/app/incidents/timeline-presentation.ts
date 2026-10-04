import { TranslationKey, t } from '../i18n/i18n';
import { measurement } from '../ui/formats';
import { IncidentEvent } from './incidents.api';

/** What the timeline says about an event: one line, and sometimes a detail below it. */
export interface EventText {
  title: string;
  detail: string | null;
}

const CHANNELS: Readonly<Record<string, TranslationKey>> = {
  email: 'incidents.timeline.channelEmail',
  telegram: 'incidents.timeline.channelTelegram',
};

const OPERATORS: Readonly<Record<string, TranslationKey>> = {
  gt: 'operators.gt',
  ge: 'operators.ge',
  lt: 'operators.lt',
  le: 'operators.le',
};

const REASONS: Readonly<Record<string, TranslationKey>> = {
  not_acknowledged: 'incidents.reasons.not_acknowledged',
  level_reached_nobody: 'incidents.reasons.level_reached_nobody',
  level_removed: 'incidents.reasons.level_removed',
  no_email: 'incidents.reasons.no_email',
  no_telegram: 'incidents.reasons.no_telegram',
  incident_acknowledged: 'incidents.reasons.incident_acknowledged',
  incident_resolved: 'incidents.reasons.incident_resolved',
};

/**
 * Why an alert was skipped or a level expired, in words. The workers record a code with its
 * parameters (VIG-40); events from before then carry Spanish text instead, shown as it is.
 */
export function reasonText(code: unknown, params: unknown, legacy: unknown): string | null {
  const key = typeof code === 'string' ? REASONS[code] : undefined;
  if (key) return t(key, (params ?? {}) as Record<string, unknown>);
  return text(legacy) ?? (typeof code === 'string' ? code : null);
}

/** "más de", "less than"... or the operator itself if it is not a known one. */
export function operatorText(operator: unknown): string {
  const key = OPERATORS[String(operator)];
  return key ? t(key) : String(operator);
}

/**
 * One event of the incident's timeline in words (SPEC: incident_events.event_type). Events
 * store ids; the API adds the names. An unknown type still shows, by its own name.
 */
export function eventText(event: IncidentEvent): EventText {
  const p = event.payload;
  const who = event.actor_name ?? t('incidents.timeline.someone');
  const recipient = event.contact_name ?? t('incidents.timeline.aContact');
  const channelKey = CHANNELS[String(p['channel'])];
  const channel = channelKey ? t(channelKey) : String(p['channel'] ?? '');
  const level =
    typeof p['level_order'] === 'number'
      ? t('incidents.timeline.level', { level: p['level_order'] })
      : null;
  const sent = { recipient, channel };
  const reason = reasonText(p['reason_code'], p['reason_params'], p['reason']);
  // A channel's error is the provider's own technical message: shown as it is.
  switch (event.event_type) {
    case 'opened':
      return { title: t('incidents.timeline.opened'), detail: openingDetail(p) };
    case 'reading_added':
      return {
        title: t('incidents.timeline.readingAdded', { value: number(p['value']) }),
        detail: null,
      };
    case 'alert_sent':
      return { title: t('incidents.timeline.alertSent', sent), detail: level };
    case 'alert_failed':
      return p['final']
        ? { title: t('incidents.timeline.alertFailedFinal', sent), detail: text(p['error']) ?? level }
        : { title: t('incidents.timeline.alertFailedRetry', sent), detail: level };
    case 'alert_skipped':
      return { title: t('incidents.timeline.alertSkipped', sent), detail: reason };
    case 'escalated':
      return {
        title: t('incidents.timeline.escalated', { level: p['to_level'] }),
        detail: reason,
      };
    case 'escalation_exhausted':
      return { title: t('incidents.timeline.exhausted'), detail: reason };
    case 'station_recovered':
      return { title: t('incidents.timeline.recovered'), detail: null };
    case 'acknowledged':
      return {
        title: t('incidents.timeline.acknowledged', { who }),
        detail: event.actor_type === 'contact' ? t('incidents.timeline.fromAlert') : null,
      };
    case 'resolved':
      return {
        title:
          p['resolution'] === 'false_alarm'
            ? t('incidents.timeline.falseAlarm', { who })
            : t('incidents.timeline.resolved', { who }),
        detail: null,
      };
    case 'comment':
      return { title: t('incidents.timeline.comment', { who }), detail: text(p['text']) };
    default:
      return { title: event.event_type, detail: null };
  }
}

/** "Regla: más de 3.5 en 2 lecturas seguidas · valor 4.6". */
function openingDetail(p: Record<string, unknown>): string | null {
  const params = (p['rule_params'] ?? {}) as Record<string, unknown>;
  let rule: string | null = null;
  if (p['rule_type'] === 'threshold') {
    rule = t('incidents.timeline.thresholdRule', {
      operator: operatorText(params['operator']),
      value: number(params['value']),
      readings: t('incidents.timeline.consecutive', { count: Number(params['consecutive']) }),
    });
  } else if (p['rule_type'] === 'rate_of_change') {
    rule = t('incidents.timeline.rateRule', {
      direction: t(params['direction'] === 'up' ? 'incidents.timeline.up' : 'incidents.timeline.down'),
      delta: number(params['delta']),
      minutes: params['window_minutes'],
    });
  } else if (p['rule_type'] === 'silence') {
    rule = t('incidents.timeline.silenceRule');
  }
  const parts = rule ? [t('incidents.timeline.rule', { rule })] : [];
  if (typeof p['trigger_value'] === 'number') {
    const value = number(p['trigger_value']);
    // For silence it is the last known reading, not one that fired the rule (as in the email).
    parts.push(
      p['rule_type'] === 'silence'
        ? t('incidents.timeline.lastValue', { value })
        : t('incidents.timeline.value', { value }),
    );
  }
  return parts.length > 0 ? parts.join(' · ') : null;
}

function number(value: unknown): string {
  return typeof value === 'number' ? measurement(value) : String(value);
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}
