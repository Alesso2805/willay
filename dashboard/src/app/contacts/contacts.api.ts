import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { settings } from '../settings';
import { Language } from '../i18n/i18n';

export interface ContactGroupRef {
  id: string;
  name: string;
}

/** docs/openapi.json › ContactOut. Whether Telegram is linked, never the chat. */
export interface Contact {
  id: string;
  full_name: string;
  email: string | null;
  /** Of its alerts (emails, Telegram, the confirmation page); null: the organization's. */
  language: Language | null;
  telegram_linked: boolean;
  /** While a generated link still works and the contact has not used it. */
  telegram_link_expires_at: string | null;
  groups: ContactGroupRef[];
  /** Alerts or an acknowledgement name it: it cannot be deleted, only removed from its groups. */
  has_history: boolean;
}

/** docs/openapi.json › ContactIn. An empty email means none. */
export interface ContactInput {
  full_name: string;
  email: string | null;
  language: Language | null;
}

/** Shown once: only its hash is stored. */
export interface TelegramLink {
  url: string;
  expires_at: string;
}

@Injectable({ providedIn: 'root' })
export class ContactsApi {
  private readonly http = inject(HttpClient);
  private readonly url = `${settings.apiUrl}/v1/contacts`;

  list(): Observable<Contact[]> {
    return this.http.get<Contact[]>(this.url);
  }

  create(contact: ContactInput): Observable<Contact> {
    return this.http.post<Contact>(this.url, contact);
  }

  update(id: string, contact: ContactInput): Observable<Contact> {
    return this.http.put<Contact>(`${this.url}/${id}`, contact);
  }

  /** 409 if it has history. */
  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}`);
  }

  removeFromGroups(id: string): Observable<Contact> {
    return this.http.post<Contact>(`${this.url}/${id}/remove-from-groups`, null);
  }

  /** 503 if the bot is not configured. */
  telegramLink(id: string): Observable<TelegramLink> {
    return this.http.post<TelegramLink>(`${this.url}/${id}/telegram-link`, null);
  }

  unlinkTelegram(id: string): Observable<Contact> {
    return this.http.delete<Contact>(`${this.url}/${id}/telegram`);
  }
}
