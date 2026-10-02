import { HttpErrorResponse } from '@angular/common/http';
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

/** The API's limit for a comment (incidents/domain/comments.py). */
export const MAX_COMMENT_LENGTH = 2000;

/**
 * Why an action on an incident failed, for the operator. A 409 means someone changed it first
 * (for example, a contact acknowledged from Telegram): the API explains it in Spanish.
 */
export function actionProblem(error: unknown): string {
  if (!(error instanceof HttpErrorResponse)) return 'No se pudo completar. Intenta de nuevo.';
  if (error.status === 409 && typeof error.error?.detail === 'string') {
    return `${error.error.detail} Se actualizó el incidente.`;
  }
  if (error.status === 403) return 'Tu rol no permite hacer esto.';
  if (error.status === 404) return 'El incidente ya no existe o no es de tu organización.';
  if (error.status === 422) {
    return `El comentario debe tener entre 1 y ${MAX_COMMENT_LENGTH} caracteres.`;
  }
  return 'No se pudo completar. Intenta de nuevo.';
}
