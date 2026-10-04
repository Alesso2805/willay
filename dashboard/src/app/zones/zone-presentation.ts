import { HttpErrorResponse } from '@angular/common/http';
import { t } from '../i18n/i18n';
import { RISK_LEVEL_STATES } from '../ui/visual-states';
import { Position, RiskLevel } from './zones.api';

export const RISK_LEVELS: readonly RiskLevel[] = ['low', 'medium', 'high', 'critical'];

/** Label and color come from the visual catalog (VIG-33); only the map stroke lives here. */
export function riskLabel(level: RiskLevel): string {
  return t(RISK_LEVEL_STATES[level].labelKey);
}

/**
 * Color reinforces but is never the only signal (WCAG): the level also appears as text in the
 * list and in the map tooltip, and the stroke style changes per level.
 */
export const RISK_STYLES: Record<RiskLevel, { color: string; dashArray?: string; weight: number }> = {
  low: { color: RISK_LEVEL_STATES.low.map, dashArray: '2 6', weight: 2 },
  medium: { color: RISK_LEVEL_STATES.medium.map, dashArray: '8 6', weight: 2 },
  high: { color: RISK_LEVEL_STATES.high.map, weight: 3 },
  critical: { color: RISK_LEVEL_STATES.critical.map, weight: 4 },
};

export interface SaveProblem {
  message: string;
  /** Point reported by PostGIS, e.g. "Self-intersection[-76.65 -11.95]". */
  point: Position | null;
}

/** Turns an API error from saving a zone into a message for the operator. */
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

/** Extracts the point from an ST_IsValidReason reason: "Reason[lon lat]". */
export function problemPoint(reason: string): Position | null {
  const match = /\[(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)\]$/.exec(reason);
  return match ? [Number(match[1]), Number(match[2])] : null;
}
