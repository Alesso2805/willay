import { HttpErrorResponse } from '@angular/common/http';
import { t } from '../i18n/i18n';
import { measurement } from '../ui/formats';
import {
  RateOfChangeParams,
  Rule,
  RulePreview,
  ThresholdOperator,
  ThresholdParams,
} from './rules.api';

export const OPERATORS: readonly ThresholdOperator[] = ['gt', 'ge', 'lt', 'le'];

/** "Mayor que", "Less than or equal to"… */
export function operatorLabel(operator: ThresholdOperator): string {
  return t(`rules.operators.${operator}`);
}

/** Silence needs to know the station's interval and K to say when it fires. */
export interface StationTiming {
  expected_interval_s: number;
  silence_multiplier: number;
}

/** What the rule watches, in words: "Mayor que 3.5 m durante 2 lecturas seguidas". */
export function ruleSummary(rule: Rule, timing?: StationTiming): string {
  const unit = rule.station?.unit ?? '';
  switch (rule.type) {
    case 'threshold': {
      const p = rule.params as ThresholdParams;
      return t('rules.thresholdSummary', {
        operator: operatorLabel(p.operator),
        value: measurement(p.value),
        unit,
        run: t('rules.run', { count: p.consecutive }),
      });
    }
    case 'rate_of_change': {
      const p = rule.params as RateOfChangeParams;
      return t('rules.rateSummary', {
        verb: t(p.direction === 'down' ? 'rules.drops' : 'rules.rises'),
        delta: measurement(p.delta),
        unit,
        minutes: p.window_minutes,
      });
    }
    case 'silence':
      if (!rule.station) return t('rules.silenceAnyStation');
      if (!timing) return t('rules.silenceStation');
      return t('rules.silenceTimed', {
        multiplier: timing.silence_multiplier,
        interval: timing.expected_interval_s,
        duration: silenceText(timing),
      });
  }
}

export function silenceText(timing: StationTiming): string {
  const seconds = timing.expected_interval_s * timing.silence_multiplier;
  return seconds % 60 === 0 ? `${seconds / 60} min` : `${seconds} s`;
}

/** "Espera 30 min tras resolver": the cooldown, which the form edits in minutes. */
export function cooldownText(seconds: number): string {
  if (seconds === 0) return t('rules.cooldownNone');
  const minutes = seconds / 60;
  return t('rules.cooldownWait', {
    minutes: Number.isInteger(minutes) ? minutes : minutes.toFixed(1),
  });
}

/** "Habría abierto 2 incidentes en las últimas 24 h". */
export function previewSummary(station: RulePreview['stations'][number], silence: boolean): string {
  const count = station.firings.length;
  if (!silence && station.readings.length === 0) return t('rules.previewNoReadings');
  if (count === 0) return t('rules.previewNone');
  return t('rules.previewWould', { count });
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
      item?.type === 'value_error' && typeof item.msg === 'string'
        ? item.msg
        : t('rules.invalidValue');
  }
  return errors;
}

export function ruleProblem(error: unknown): string {
  if (!(error instanceof HttpErrorResponse)) return t('ui.genericProblem');
  if (error.status === 403) return t('rules.forbidden');
  if (error.status === 404) return t('rules.notFound');
  if (error.status === 422) return t('ui.checkFields');
  return t('ui.genericProblem');
}
