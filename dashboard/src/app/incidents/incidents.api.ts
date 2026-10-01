import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { settings } from '../settings';

export type IncidentStatus = 'open' | 'acknowledged' | 'resolved';

/** docs/openapi.json › IncidentOut. Just enough for the summary; VIG-34 adds the inbox. */
export interface Incident {
  id: string;
  zone_name: string;
  station_code: string | null;
  rule_type: string;
  severity: 'info' | 'warning' | 'critical';
  status: IncidentStatus;
  current_level: number;
  opened_at: string;
  escalation_exhausted_at: string | null;
}

@Injectable({ providedIn: 'root' })
export class IncidentsApi {
  private readonly http = inject(HttpClient);
  private readonly url = `${settings.apiUrl}/v1/incidents`;

  /** Newest first; `status` is repeated in the URL once per requested status. */
  list(statuses: readonly IncidentStatus[], limit = 500): Observable<Incident[]> {
    const params = new HttpParams({ fromObject: { status: [...statuses], limit } });
    return this.http.get<Incident[]>(this.url, { params });
  }
}
