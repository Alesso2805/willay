import { measurement } from '../ui/formats';
import { IncidentEvent } from './incidents.api';

/** What the timeline says about an event: one line, and sometimes a detail below it. */
export interface EventText {
  title: string;
  detail: string | null;
}

const CHANNELS: Record<string, string> = { email: 'correo', telegram: 'Telegram' };

const OPERATORS: Record<string, string> = {
  gt: 'más de',
  ge: 'desde',
  lt: 'menos de',
  le: 'hasta',
};

/**
 * One event of the incident's timeline in words (SPEC: incident_events.event_type). Events
 * store ids; the API adds the names. An unknown type still shows, by its own name.
 */
export function eventText(event: IncidentEvent): EventText {
  const p = event.payload;
  const who = event.actor_name ?? 'alguien';
  const recipient = event.contact_name ?? 'un contacto';
  const channel = CHANNELS[String(p['channel'])] ?? String(p['channel'] ?? '');
  const level = typeof p['level_order'] === 'number' ? `nivel ${p['level_order']}` : null;
  switch (event.event_type) {
    case 'opened':
      return { title: 'Se abrió el incidente', detail: openingDetail(p) };
    case 'reading_added':
      return { title: `Empeoró: nueva lectura de ${number(p['value'])}`, detail: null };
    case 'alert_sent':
      return { title: `Alerta enviada a ${recipient} por ${channel}`, detail: level };
    case 'alert_failed':
      return p['final']
        ? { title: `No se pudo avisar a ${recipient} por ${channel}`, detail: text(p['error']) ?? level }
        : { title: `Falló un envío a ${recipient} por ${channel}; se reintentará`, detail: level };
    case 'alert_skipped':
      return { title: `No se avisó a ${recipient} por ${channel}`, detail: text(p['reason']) };
    case 'escalated':
      return { title: `Escaló al nivel ${p['to_level']}`, detail: text(p['reason']) };
    case 'escalation_exhausted':
      return { title: 'Se agotó el escalamiento', detail: text(p['reason']) };
    case 'station_recovered':
      return { title: 'La estación volvió a reportar', detail: null };
    case 'acknowledged':
      return {
        title: `Confirmado por ${who}`,
        detail: event.actor_type === 'contact' ? 'Desde su alerta' : null,
      };
    case 'resolved':
      return {
        title:
          p['resolution'] === 'false_alarm'
            ? `Marcado como falsa alarma por ${who}`
            : `Resuelto por ${who}`,
        detail: null,
      };
    case 'comment':
      return { title: `Comentario de ${who}`, detail: text(p['text']) };
    default:
      return { title: event.event_type, detail: null };
  }
}

/** "Regla: más de 3.5 en 2 lecturas seguidas · valor 4.6". */
function openingDetail(p: Record<string, unknown>): string | null {
  const params = (p['rule_params'] ?? {}) as Record<string, unknown>;
  let rule: string | null = null;
  if (p['rule_type'] === 'threshold') {
    const count = Number(params['consecutive']);
    const readings = count === 1 ? '1 lectura' : `${count} lecturas seguidas`;
    rule = `${OPERATORS[String(params['operator'])] ?? params['operator']} ${number(params['value'])} en ${readings}`;
  } else if (p['rule_type'] === 'rate_of_change') {
    const direction = params['direction'] === 'up' ? 'subida' : 'bajada';
    rule = `${direction} de más de ${number(params['delta'])} en ${params['window_minutes']} min`;
  } else if (p['rule_type'] === 'silence') {
    rule = 'la estación dejó de reportar';
  }
  const parts = rule ? [`Regla: ${rule}`] : [];
  // For silence it is the last known reading, not one that fired the rule (as in the email).
  const label = p['rule_type'] === 'silence' ? 'último valor' : 'valor';
  if (typeof p['trigger_value'] === 'number') parts.push(`${label} ${number(p['trigger_value'])}`);
  return parts.length > 0 ? parts.join(' · ') : null;
}

function number(value: unknown): string {
  return typeof value === 'number' ? measurement(value) : String(value);
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}
