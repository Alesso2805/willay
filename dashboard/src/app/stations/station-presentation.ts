import { HttpErrorResponse } from '@angular/common/http';
import { Variable, ZonePosition } from './stations.api';

export const VARIABLES: readonly Variable[] = ['discharge', 'water_level', 'rainfall'];

export const VARIABLE_LABELS: Record<Variable, string> = {
  discharge: 'Caudal',
  water_level: 'Nivel',
  rainfall: 'Lluvia',
};

/** Espejo de la regla del backend: la unidad sale de la variable (no se elige). */
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

/** "hace 12 s", "hace 3 min"... a partir de una fecha ISO. */
export function ageText(iso: string, now: number): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (seconds < 60) return `hace ${seconds} s`;
  if (seconds < 3600) return `hace ${Math.floor(seconds / 60)} min`;
  if (seconds < 86_400) return `hace ${Math.floor(seconds / 3600)} h`;
  return `hace ${Math.floor(seconds / 86_400)} d`;
}

/** Traduce un error al guardar una estación a un mensaje para el operador. */
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
