import { IncidentState } from '../ui/visual-states';
import { Incident } from './incidents.api';

/** The same wording as the alert emails and Telegram messages (alerts/domain/email.py). */
const CAUSES: Record<string, string> = {
  threshold: 'Valor fuera de límite',
  rate_of_change: 'Cambio brusco',
  silence: 'Estación sin reportar',
};

export function causeLabel(ruleType: string): string {
  return CAUSES[ruleType] ?? ruleType;
}

/**
 * An open incident whose escalation ran out of levels shows as exhausted (SPEC: in red). Once
 * someone acknowledges it, it is acknowledged: somebody is handling it.
 */
export function incidentState(incident: Incident): IncidentState {
  return incident.status === 'open' && incident.escalation_exhausted_at !== null
    ? 'exhausted'
    : incident.status;
}
