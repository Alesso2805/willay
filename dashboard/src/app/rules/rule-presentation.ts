import { HttpErrorResponse } from '@angular/common/http';
import { measurement } from '../ui/formats';
import {
  RateOfChangeParams,
  Rule,
  RulePreview,
  ThresholdOperator,
  ThresholdParams,
} from './rules.api';

export const OPERATOR_LABELS: Readonly<Record<ThresholdOperator, string>> = {
  gt: 'Mayor que',
  ge: 'Mayor o igual que',
  lt: 'Menor que',
  le: 'Menor o igual que',
};

/** Silence needs to know the station's interval and K to say when it fires. */
export interface StationTiming {
  expected_interval_s: number;
  silence_multiplier: number;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** What the rule watches, in words: "Mayor que 3.5 m durante 2 lecturas seguidas". */
export function ruleSummary(rule: Rule, timing?: StationTiming): string {
  const unit = rule.station?.unit ?? '';
  switch (rule.type) {
    case 'threshold': {
      const p = rule.params as ThresholdParams;
      const run = plural(p.consecutive, 'lectura', 'lecturas seguidas');
      return `${OPERATOR_LABELS[p.operator]} ${measurement(p.value)} ${unit} durante ${run}`;
    }
    case 'rate_of_change': {
      const p = rule.params as RateOfChangeParams;
      const verb = p.direction === 'down' ? 'Baja' : 'Sube';
      return `${verb} más de ${measurement(p.delta)} ${unit} en ${p.window_minutes} min`;
    }
    case 'silence':
      if (!rule.station) return 'Cualquier estación de la zona deja de reportar (K × su intervalo)';
      if (!timing) return 'La estación deja de reportar (K × su intervalo)';
      return `Sin reportar ${timing.silence_multiplier} × ${timing.expected_interval_s} s (${silenceText(timing)})`;
  }
}

export function silenceText(timing: StationTiming): string {
  const seconds = timing.expected_interval_s * timing.silence_multiplier;
  return seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds} s`;
}

/** "Espera 30 min tras resolver": the cooldown, which the form edits in minutes. */
export function cooldownText(seconds: number): string {
  if (seconds === 0) return 'Sin espera tras resolver';
  const minutes = seconds / 60;
  return `Espera ${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)} min tras resolver`;
}

/** "Habría abierto 2 incidentes en las últimas 24 h". */
export function previewSummary(station: RulePreview['stations'][number], silence: boolean): string {
  const count = station.firings.length;
  if (!silence && station.readings.length === 0) return 'Sin lecturas en las últimas 24 h.';
  if (count === 0) return 'No habría abierto ningún incidente en las últimas 24 h.';
  return `Habría abierto ${plural(count, 'incidente', 'incidentes')} en las últimas 24 h.`;
}

/**
 * The fields of a 422, for the form: the domain's messages are already for the operator; the
 * shape checks of the API are not, so those get a generic message.
 */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof HttpErrorResponse) || error.status !== 422) return {};
  const detail: unknown = error.error?.detail;
  if (!Array.isArray(detail)) return {};
  const errors: Record<string, string> = {};
  for (const item of detail) {
    const field = Array.isArray(item?.loc) ? String(item.loc[item.loc.length - 1]) : 'form';
    errors[field] ??=
      item?.type === 'value_error' && typeof item.msg === 'string' ? item.msg : 'Valor no válido.';
  }
  return errors;
}

export function ruleProblem(error: unknown): string {
  if (!(error instanceof HttpErrorResponse)) return 'No se pudo completar. Intenta de nuevo.';
  if (error.status === 403) return 'Tu rol no permite gestionar reglas.';
  if (error.status === 404) return 'La regla ya no existe.';
  if (error.status === 422) return 'Revisa los campos marcados.';
  return 'No se pudo completar. Intenta de nuevo.';
}
