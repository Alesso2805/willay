import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { Language } from '../i18n/i18n';
import { settings } from '../settings';

/** docs/openapi.json › OrganizationOut. */
export interface Organization {
  id: string;
  name: string;
  /** The language of the alerts of its contacts that chose none. */
  language: Language;
  /** IANA name: every time Willay writes for it uses it. */
  timezone: string;
}

/** VIG-44: every role reads it; an admin changes its language and time zone. */
@Injectable({ providedIn: 'root' })
export class OrganizationApi {
  private readonly http = inject(HttpClient);
  private readonly url = `${settings.apiUrl}/v1/organization`;

  get(): Observable<Organization> {
    return this.http.get<Organization>(this.url);
  }

  /** 422 for a time zone that is not an IANA name. */
  update(language: Language, timezone: string): Observable<Organization> {
    return this.http.put<Organization>(this.url, { language, timezone });
  }
}
