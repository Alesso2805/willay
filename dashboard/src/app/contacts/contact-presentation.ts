import { HttpErrorResponse } from '@angular/common/http';
import { t } from '../i18n/i18n';
import { ContactChannelState } from '../ui/visual-states';
import { Contact } from './contacts.api';

/** Its channels, or "none": a contact nobody can reach is flagged on the screen (SPEC). */
export function channelStates(contact: Contact): ContactChannelState[] {
  const states: ContactChannelState[] = [];
  if (contact.email) states.push('email');
  if (contact.telegram_linked) states.push('telegram');
  if (states.length === 0) states.push('none');
  if (!contact.telegram_linked && contact.telegram_link_expires_at) states.push('pending');
  return states;
}

/** Why an action on a contact or group failed, for the admin. The API explains a 409 and a 503. */
export function contactProblem(error: unknown, what: 'contact' | 'group' = 'contact'): string {
  if (!(error instanceof HttpErrorResponse)) return t('ui.genericProblem');
  const detail = error.error?.detail;
  if ((error.status === 409 || error.status === 503) && typeof detail === 'string') return detail;
  if (error.status === 403) return t('contacts.forbidden');
  if (error.status === 404) return t(what === 'group' ? 'contacts.groupGone' : 'contacts.contactGone');
  if (error.status === 422) {
    const first = Array.isArray(detail) ? detail[0] : null;
    if (typeof first?.msg === 'string') return first.msg;
    return t(what === 'group' ? 'contacts.checkGroup' : 'contacts.checkContact');
  }
  return t('ui.genericProblem');
}
