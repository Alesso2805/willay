import { HttpErrorResponse } from '@angular/common/http';
import { TranslationKey, t } from '../i18n/i18n';
import { IncidentState } from '../ui/visual-states';
import { Incident } from './incidents.api';

/** The same wording as the alert emails and Telegram messages (backend locales, `alerts.cause`). */
const CAUSES: Readonly<Record<string, TranslationKey>> = {
  threshold: 'causes.threshold',
  rate_of_change: 'causes.rate_of_change',
  silence: 'causes.silence',
};

export function causeLabel(ruleType: string): string {
  return CAUSES[ruleType] ? t(CAUSES[ruleType]) : ruleType;
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
 * (for example, a contact acknowledged from Telegram): the API explains it.
 */
export function actionProblem(error: unknown): string {
  if (!(error instanceof HttpErrorResponse)) return t('incidents.problems.generic');
  if (error.status === 409 && typeof error.error?.detail === 'string') {
    return t('incidents.problems.conflict', { detail: error.error.detail });
  }
  if (error.status === 403) return t('incidents.problems.forbidden');
  if (error.status === 404) return t('incidents.problems.notFound');
  if (error.status === 422) return t('incidents.problems.commentLength', { max: MAX_COMMENT_LENGTH });
  return t('incidents.problems.generic');
}
