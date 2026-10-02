import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { settings } from '../settings';

export interface Ref {
  id: string;
  name: string;
}

/** docs/openapi.json › GroupOut. */
export interface ContactGroup {
  id: string;
  name: string;
  /** A label for the admin: alerting does not depend on it. */
  zone: Ref | null;
  /** Contacts, by name. */
  members: Ref[];
  /** The policies that notify it: while there is any, it cannot be deleted. */
  policies: Ref[];
}

/** docs/openapi.json › GroupIn. The member list is sent whole. */
export interface GroupInput {
  name: string;
  zone_id: string | null;
  member_ids: string[];
}

@Injectable({ providedIn: 'root' })
export class GroupsApi {
  private readonly http = inject(HttpClient);
  private readonly url = `${settings.apiUrl}/v1/contact-groups`;

  list(): Observable<ContactGroup[]> {
    return this.http.get<ContactGroup[]>(this.url);
  }

  create(group: GroupInput): Observable<ContactGroup> {
    return this.http.post<ContactGroup>(this.url, group);
  }

  update(id: string, group: GroupInput): Observable<ContactGroup> {
    return this.http.put<ContactGroup>(`${this.url}/${id}`, group);
  }

  /** 409 if a policy notifies it, naming the policy. */
  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}`);
  }
}
