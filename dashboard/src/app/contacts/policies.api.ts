import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { settings } from '../settings';

export type Channel = 'email' | 'telegram';

/** docs/openapi.json › PolicyOut: ordered levels, each notifying groups through a channel. */
export interface Policy {
  id: string;
  name: string;
  levels: {
    level_order: number;
    /** How long nobody may acknowledge before the next level is alerted (or it is exhausted). */
    wait_s: number;
    targets: { contact_group_id: string; contact_group_name: string; channel: Channel }[];
  }[];
  created_at: string;
}

/** docs/openapi.json › PolicyIn. A level's order is its position in the list. */
export interface PolicyInput {
  name: string;
  levels: { wait_s: number; targets: { contact_group_id: string; channel: Channel }[] }[];
}

/** VIG-24's API: everyone reads; admin creates, edits and deletes. */
@Injectable({ providedIn: 'root' })
export class PoliciesApi {
  private readonly http = inject(HttpClient);
  private readonly url = `${settings.apiUrl}/v1/escalation-policies`;

  list(): Observable<Policy[]> {
    return this.http.get<Policy[]>(this.url);
  }

  create(policy: PolicyInput): Observable<Policy> {
    return this.http.post<Policy>(this.url, policy);
  }

  /** It applies to ongoing incidents too: the escalation reads the policy when it escalates. */
  update(id: string, policy: PolicyInput): Observable<Policy> {
    return this.http.put<Policy>(`${this.url}/${id}`, policy);
  }

  /** 409 while a rule uses it. */
  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}`);
  }
}
