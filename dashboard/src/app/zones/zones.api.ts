import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { settings } from '../settings';

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

/** GeoJSON coordinates: [longitude, latitude]. */
export type Position = [number, number];

export interface PolygonGeometry {
  type: 'Polygon';
  coordinates: Position[][];
}

export interface MultiPolygonGeometry {
  type: 'MultiPolygon';
  coordinates: Position[][][];
}

/** /v1/zones response (docs/openapi.json › ZoneOut). */
export interface Zone {
  id: string;
  name: string;
  description: string | null;
  risk_level: RiskLevel;
  population_estimate: number | null;
  is_active: boolean;
  geometry: MultiPolygonGeometry;
  created_at: string;
  updated_at: string;
}

/** POST and PUT body (docs/openapi.json › ZoneIn). */
export interface ZoneInput {
  name: string;
  description: string | null;
  risk_level: RiskLevel;
  population_estimate: number | null;
  geometry: PolygonGeometry | MultiPolygonGeometry;
  is_active: boolean;
}

@Injectable({ providedIn: 'root' })
export class ZonesApi {
  private readonly http = inject(HttpClient);
  private readonly url = `${settings.apiUrl}/v1/zones`;

  list(includeInactive = false): Observable<Zone[]> {
    return this.http.get<Zone[]>(this.url, { params: { include_inactive: includeInactive } });
  }

  create(zone: ZoneInput): Observable<Zone> {
    return this.http.post<Zone>(this.url, zone);
  }

  update(id: string, zone: ZoneInput): Observable<Zone> {
    return this.http.put<Zone>(`${this.url}/${id}`, zone);
  }

  /** The API deactivates (does not delete): rules and incidents keep their zone. */
  deactivate(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}`);
  }
}
