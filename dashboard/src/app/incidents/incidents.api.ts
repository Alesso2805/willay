import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { settings } from '../settings';

export type IncidentStatus = 'open' | 'acknowledged' | 'resolved';
export type IncidentSeverity = 'info' | 'warning' | 'critical';

/** docs/openapi.json › IncidentOut: what the summary, the live map and the inbox show. */
export interface Incident {
  id: string;
  zone_id: string;
  zone_name: string;
  station_id: string | null;
  station_code: string | null;
  rule_type: string;
  severity: IncidentSeverity;
  status: IncidentStatus;
  current_level: number;
  opened_at: string;
  escalation_exhausted_at: string | null;
}

/** docs/openapi.json › IncidentEventOut. Names are resolved by the API; payloads hold ids. */
export interface IncidentEvent {
  id: number;
  occurred_at: string;
  event_type: string;
  actor_type: 'system' | 'user' | 'contact';
  actor_id: string | null;
  actor_name: string | null;
  contact_name: string | null;
  payload: Record<string, unknown>;
}

/**
 * docs/openapi.json › IncidentAlertOut. `email` only comes to users who may see contact
 * details (operator, admin); a Telegram chat never leaves the API.
 */
export interface IncidentAlert {
  id: string;
  level_order: number;
  contact_id: string;
  contact_name: string;
  channel: 'email' | 'telegram';
  status: 'pending' | 'sent' | 'failed' | 'skipped' | 'acknowledged';
  attempts: number;
  sent_at: string | null;
  acknowledged_at: string | null;
  skipped_reason: string | null;
  email: string | null;
}

/**
 * docs/openapi.json › IncidentReadingsOut: the readings around the opening. `evidence` means
 * they expired and these are the ones copied into the opened event.
 */
export interface IncidentReadings {
  station_code: string | null;
  unit: string | null;
  window_start: string;
  window_end: string;
  source: 'readings' | 'evidence';
  readings: { measured_at: string; value: number }[];
  threshold: { operator: string; value: number } | null;
}

/** docs/openapi.json › IncidentDetailOut: the incident with its timeline, oldest first. */
export interface IncidentDetail extends Incident {
  trigger_value: number | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  resolution: 'resolved' | 'false_alarm' | null;
  timeline: IncidentEvent[];
}

@Injectable({ providedIn: 'root' })
export class IncidentsApi {
  private readonly http = inject(HttpClient);
  private readonly url = `${settings.apiUrl}/v1/incidents`;

  /** Newest first; each filter is repeated in the URL once per value, and an empty one means all. */
  list(
    statuses: readonly IncidentStatus[],
    severities: readonly IncidentSeverity[] = [],
    limit = 500,
  ): Observable<Incident[]> {
    const query: Record<string, number | readonly string[]> = { status: statuses };
    if (severities.length > 0) query['severity'] = severities;
    query['limit'] = limit;
    return this.http.get<Incident[]>(this.url, { params: new HttpParams({ fromObject: query }) });
  }

  /** The incident with its timeline. */
  get(id: string): Observable<IncidentDetail> {
    return this.http.get<IncidentDetail>(`${this.url}/${id}`);
  }

  /** The readings around its opening, for the chart. */
  readings(id: string): Observable<IncidentReadings> {
    return this.http.get<IncidentReadings>(`${this.url}/${id}/readings`);
  }

  /** Responder and above; only an open incident (409 otherwise). */
  acknowledge(id: string): Observable<Incident> {
    return this.http.post<Incident>(`${this.url}/${id}/acknowledge`, null);
  }

  /** Operator and above; final (409 if already resolved). */
  resolve(id: string, resolution: 'resolved' | 'false_alarm'): Observable<Incident> {
    return this.http.post<Incident>(`${this.url}/${id}/resolve`, { resolution });
  }

  /** Responder and above, in any status; the API trims it and requires 1 to 2000 characters. */
  comment(id: string, text: string): Observable<IncidentEvent> {
    return this.http.post<IncidentEvent>(`${this.url}/${id}/comments`, { text });
  }

  /** Its alerts by level, recipient and channel. */
  alerts(id: string): Observable<IncidentAlert[]> {
    return this.http.get<IncidentAlert[]>(`${this.url}/${id}/alerts`);
  }
}
