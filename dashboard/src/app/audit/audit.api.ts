import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { settings } from '../settings';

export type EntityType =
  'risk_zone' | 'station' | 'rule' | 'escalation_policy' | 'contact' | 'contact_group';

export interface Author {
  id: string;
  name: string;
}

/** docs/openapi.json › AuditEntryOut. */
export interface AuditEntry {
  id: number;
  at: string;
  /** null: nobody from the organization, e.g. the contact themselves from Telegram. */
  actor: Author | null;
  entity_type: string;
  entity_id: string;
  /** Its current name, for entries whose snapshot has none; null once it was deleted. */
  entity_name: string | null;
  action: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface AuditPage {
  items: AuditEntry[];
  next_cursor: string | null;
}

export interface AuditQuery {
  entity_type?: EntityType;
  entity_id?: string;
  actor_id?: string;
  /** Inclusive, as an instant (ISO). */
  since?: string;
  /** Exclusive, as an instant (ISO). */
  until?: string;
}

@Injectable({ providedIn: 'root' })
export class AuditApi {
  private readonly http = inject(HttpClient);
  private readonly url = `${settings.apiUrl}/v1/audit`;

  page(query: AuditQuery, cursor: string | null): Observable<AuditPage> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(query)) {
      if (value) params = params.set(key, value);
    }
    if (cursor) params = params.set('cursor', cursor);
    return this.http.get<AuditPage>(this.url, { params });
  }

  authors(): Observable<Author[]> {
    return this.http.get<Author[]>(`${this.url}/authors`);
  }
}
