import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { settings } from '../settings';

export type Variable = 'water_level' | 'discharge' | 'rainfall';
export type Source = 'sensor' | 'simulator';
export type StationStatus = 'active' | 'inactive';
export type ZonePosition = 'upstream' | 'in_zone' | 'downstream';

export interface PointGeometry {
  type: 'Point';
  /** [longitud, latitud] */
  coordinates: [number, number];
}

export interface ZoneAssignment {
  zone_id: string;
  position: ZonePosition;
}

/** docs/openapi.json › StationOut */
export interface Station {
  id: string;
  code: string;
  name: string;
  variable: Variable;
  unit: string;
  location: PointGeometry;
  source: Source;
  expected_interval_s: number;
  silence_multiplier: number;
  status: StationStatus;
  zones: ZoneAssignment[];
  has_zone: boolean;
  heartbeat: { last_seen_at: string; last_measured_at: string; last_value: number | null } | null;
  api_key_rotated_at: string;
  created_at: string;
}

/** docs/openapi.json › StationBodyIn (PUT). El código no se envía: no cambia. */
export interface StationInput {
  name: string;
  variable: Variable;
  location: PointGeometry;
  source: Source;
  expected_interval_s: number;
  silence_multiplier: number;
  status: StationStatus;
  zones: ZoneAssignment[];
}

/** Respuesta de crear o rotar: la única vez que la API devuelve la clave en claro. */
export interface IssuedKey {
  station: Station;
  api_key: string;
}

@Injectable({ providedIn: 'root' })
export class StationsApi {
  private readonly http = inject(HttpClient);
  private readonly url = `${settings.apiUrl}/v1/stations`;

  list(includeInactive = false): Observable<Station[]> {
    return this.http.get<Station[]>(this.url, { params: { include_inactive: includeInactive } });
  }

  create(code: string, station: StationInput): Observable<IssuedKey> {
    return this.http.post<IssuedKey>(this.url, { code, ...station });
  }

  update(id: string, station: StationInput): Observable<Station> {
    return this.http.put<Station>(`${this.url}/${id}`, station);
  }

  deactivate(id: string): Observable<void> {
    return this.http.delete<void>(`${this.url}/${id}`);
  }

  rotateKey(id: string): Observable<IssuedKey> {
    return this.http.post<IssuedKey>(`${this.url}/${id}/api-key`, null);
  }
}
