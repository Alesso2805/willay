import { HttpErrorResponse } from '@angular/common/http';
import { StationState } from '../ui/visual-states';
import { Station, Variable, ZonePosition } from './stations.api';

export const VARIABLES: readonly Variable[] = ['discharge', 'water_level', 'rainfall'];

export const VARIABLE_LABELS: Record<Variable, string> = {
  discharge: 'Caudal',
  water_level: 'Nivel',
  rainfall: 'Lluvia',
};

/** Mirrors the backend rule: the unit follows from the variable (it is not chosen). */
export const UNITS: Record<Variable, string> = {
  discharge: 'm3/s',
  water_level: 'm',
  rainfall: 'mm',
};

export const POSITION_LABELS: Record<ZonePosition, string> = {
  upstream: 'Aguas arriba',
  in_zone: 'En la zona',
  downstream: 'Aguas abajo',
};

/**
 * Whether the station is reporting or silent, with the same rule as the `silence` worker: no
 * batches for K × expected interval. It is an approximate view using the browser clock; the
 * worker opens the incident. A station that never reported is not silent (SPEC: it has not
 * started transmitting yet), so it has no state: returns null.
 */
export function stationState(station: Station, now: number): StationState | null {
  if (station.status === 'inactive') return 'inactive';
  if (station.heartbeat === null) return null;
  const silentAfterMs = station.expected_interval_s * station.silence_multiplier * 1000;
  return now - Date.parse(station.heartbeat.last_seen_at) > silentAfterMs ? 'silent' : 'reporting';
}

/** Turns an error from saving a station into a message for the operator. */
export function stationProblem(error: unknown): string {
  if (!(error instanceof HttpErrorResponse)) return 'No se pudo guardar la estación.';
  if (error.status === 409) return 'Ya existe una estación con ese código en tu organización.';
  if (error.status === 403) return 'Tu rol no permite gestionar estaciones.';
  if (error.status === 422) {
    const detail = error.error?.detail;
    const first = Array.isArray(detail) ? detail[0] : null;
    return typeof first?.msg === 'string' ? first.msg : 'Datos inválidos.';
  }
  return 'No se pudo guardar la estación. Intenta de nuevo.';
}
