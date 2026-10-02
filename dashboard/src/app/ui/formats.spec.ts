import { ageText, localTime, valueWithUnit, wholeNumber } from './formats';

describe('wholeNumber', () => {
  it('groups thousands like in Peru', () => {
    expect(wholeNumber(45000)).toBe('45,000');
    expect(wholeNumber(800)).toBe('800');
  });
});

describe('ageText', () => {
  const now = Date.parse('2026-10-27T09:00:00Z');

  it('reads like a person would say it', () => {
    expect(ageText('2026-10-27T08:59:48Z', now)).toBe('hace 12 s');
    expect(ageText('2026-10-27T08:57:00Z', now)).toBe('hace 3 min');
    expect(ageText('2026-10-27T06:00:00Z', now)).toBe('hace 3 h');
    expect(ageText('2026-10-25T09:00:00Z', now)).toBe('hace 2 d');
    expect(ageText('2026-10-27T09:00:05Z', now)).toBe('hace 0 s'); // clock running ahead
  });
});

describe('localTime', () => {
  it('uses the organization time zone, not the browser one', () => {
    expect(localTime('2026-09-30T23:57:04Z', 'America/Lima')).toBe('30/09/2026 18:57');
    expect(localTime('2026-09-30T23:57:04Z', 'Europe/Madrid')).toBe('01/10/2026 01:57');
  });

  it('uses a 24-hour clock', () => {
    expect(localTime('2026-10-01T05:05:00Z', 'America/Lima')).toBe('01/10/2026 00:05');
    expect(localTime('2026-09-30T23:57:04Z', 'America/Lima', true)).toBe('30/09/2026 18:57:04');
  });
});

describe('valueWithUnit', () => {
  it('rounds like the alert messages (6 significant digits) and keeps the unit', () => {
    expect(valueWithUnit(83.234, 'm3/s')).toBe('83.234 m3/s');
    expect(valueWithUnit(83.2344912, 'm3/s')).toBe('83.2345 m3/s'); // Python: f"{83.2344912:g}"
    expect(valueWithUnit(2, 'm')).toBe('2 m');
    expect(valueWithUnit(1250.5, 'mm')).toBe('1250.5 mm');
  });
});
