import { HttpErrorResponse } from '@angular/common/http';
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

/** Why an action on a contact failed, for the admin. The API explains a 409 and a 503. */
export function contactProblem(error: unknown): string {
  if (!(error instanceof HttpErrorResponse)) return 'No se pudo completar. Intenta de nuevo.';
  const detail = error.error?.detail;
  if ((error.status === 409 || error.status === 503) && typeof detail === 'string') return detail;
  if (error.status === 403) return 'Tu rol no permite gestionar contactos.';
  if (error.status === 404) return 'El contacto ya no existe.';
  if (error.status === 422) {
    const first = Array.isArray(detail) ? detail[0] : null;
    return typeof first?.msg === 'string' ? first.msg : 'Revisa los datos del contacto.';
  }
  return 'No se pudo completar. Intenta de nuevo.';
}
