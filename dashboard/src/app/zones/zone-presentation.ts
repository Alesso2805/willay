import { HttpErrorResponse } from '@angular/common/http';
import { Position, RiskLevel } from './zones.api';

export const RISK_LEVELS: readonly RiskLevel[] = ['low', 'medium', 'high', 'critical'];

export const RISK_LABELS: Record<RiskLevel, string> = {
  low: 'Bajo',
  medium: 'Medio',
  high: 'Alto',
  critical: 'Crítico',
};

/**
 * El color refuerza, pero nunca es la única señal (WCAG): el nivel también va como texto
 * en la lista y en el tooltip del mapa, y el trazo cambia de estilo por nivel.
 */
export const RISK_STYLES: Record<RiskLevel, { color: string; dashArray?: string; weight: number }> = {
  low: { color: '#15803d', dashArray: '2 6', weight: 2 },
  medium: { color: '#a16207', dashArray: '8 6', weight: 2 },
  high: { color: '#c2410c', weight: 3 },
  critical: { color: '#b91c1c', weight: 4 },
};

export interface SaveProblem {
  message: string;
  /** Punto que señala PostGIS, p. ej. "Self-intersection[-76.65 -11.95]". */
  point: Position | null;
}

/** Traduce un error de la API al guardar una zona a un mensaje para el operador. */
export function saveProblem(error: unknown): SaveProblem {
  if (!(error instanceof HttpErrorResponse)) {
    return { message: 'No se pudo guardar la zona.', point: null };
  }
  if (error.status === 403) {
    return { message: 'Tu rol no permite gestionar zonas.', point: null };
  }
  if (error.status === 422) {
    const detail = error.error?.detail;
    const first = Array.isArray(detail) ? detail[0] : null;
    const message = typeof first?.msg === 'string' ? first.msg : 'Datos inválidos.';
    return {
      message: message.startsWith('Self-intersection')
        ? 'El polígono se cruza consigo mismo. Corrige el punto marcado en el mapa.'
        : message,
      point: problemPoint(message),
    };
  }
  return { message: 'No se pudo guardar la zona. Intenta de nuevo.', point: null };
}

/** Extrae el punto de un motivo de ST_IsValidReason: "Motivo[lon lat]". */
export function problemPoint(reason: string): Position | null {
  const match = /\[(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)\]$/.exec(reason);
  return match ? [Number(match[1]), Number(match[2])] : null;
}
