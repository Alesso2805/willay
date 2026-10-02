import { HttpErrorResponse } from '@angular/common/http';
import { cooldownText, fieldErrors, previewSummary, ruleSummary } from './rule-presentation';
import { Rule } from './rules.api';

const BASE: Rule = {
  id: 'r1',
  type: 'threshold',
  zone: { id: 'z1', name: 'Chosica' },
  station: { id: 's1', code: 'RIM-CHO-01', name: 'Puente Chosica', unit: 'm' },
  params: { operator: 'gt', value: 3.5, consecutive: 2 },
  severity: 'warning',
  escalation_policy: { id: 'p1', name: 'Protocolo Rímac' },
  cooldown_s: 1800,
  is_active: true,
  created_at: '',
  updated_at: '',
};

describe('ruleSummary', () => {
  it('says what each type watches, in the station unit', () => {
    expect(ruleSummary(BASE)).toBe('Mayor que 3.5 m durante 2 lecturas seguidas');
    expect(ruleSummary({ ...BASE, params: { operator: 'le', value: 1, consecutive: 1 } })).toBe(
      'Menor o igual que 1 m durante 1 lectura',
    );
    const drop: Rule = {
      ...BASE,
      type: 'rate_of_change',
      station: { ...BASE.station!, unit: 'm3/s' },
      params: { direction: 'down', delta: 40, window_minutes: 10 },
    };
    expect(ruleSummary(drop)).toBe('Baja más de 40 m3/s en 10 min');
  });

  it('says when a station counts as silent, from its own K and interval', () => {
    const silence: Rule = { ...BASE, type: 'silence', params: {} };
    expect(ruleSummary(silence, { expected_interval_s: 10, silence_multiplier: 3 })).toBe(
      'Sin reportar 3 × 10 s (30 s)',
    );
    expect(ruleSummary(silence, { expected_interval_s: 60, silence_multiplier: 3 })).toBe(
      'Sin reportar 3 × 60 s (3 min)',
    );
    expect(ruleSummary({ ...silence, station: null })).toContain('Cualquier estación de la zona');
  });
});

describe('cooldownText', () => {
  it('speaks in minutes', () => {
    expect(cooldownText(1800)).toBe('Espera 30 min tras resolver');
    expect(cooldownText(90)).toBe('Espera 1.5 min tras resolver');
    expect(cooldownText(0)).toBe('Sin espera tras resolver');
  });
});

describe('previewSummary', () => {
  const station = { id: 's1', code: 'RIM-CHO-01', name: 'x', unit: 'm' };
  const reading = { measured_at: '2026-10-02T10:00:00Z', value: 1 };
  it('counts the incidents it would have opened, or why there are none', () => {
    const firing = { at: '2026-10-02T10:00:00Z', value: 4 };
    const one = { station, readings: [reading], firings: [firing], truncated: false };
    expect(previewSummary(one, false)).toBe('Habría abierto 1 incidente en las últimas 24 h.');
    expect(previewSummary({ ...one, firings: [firing, firing] }, false)).toContain('2 incidentes');
    expect(previewSummary({ ...one, firings: [] }, false)).toBe(
      'No habría abierto ningún incidente en las últimas 24 h.',
    );
    expect(previewSummary({ ...one, readings: [], firings: [] }, false)).toBe(
      'Sin lecturas en las últimas 24 h.',
    );
  });
});

describe('fieldErrors', () => {
  it('keeps the API explanations and replaces its technical shape checks', () => {
    const error = new HttpErrorResponse({
      status: 422,
      error: {
        detail: [
          {
            loc: ['body', 'station_id'],
            msg: 'La estación no pertenece a esa zona.',
            type: 'value_error',
          },
          {
            loc: ['body', 'threshold', 'params', 'consecutive'],
            msg: 'Input should be ≤ 60',
            type: 'less_than_equal',
          },
        ],
      },
    });
    expect(fieldErrors(error)).toEqual({
      station_id: 'La estación no pertenece a esa zona.',
      consecutive: 'Valor no válido.',
    });
    expect(fieldErrors(new HttpErrorResponse({ status: 500 }))).toEqual({});
  });
});
