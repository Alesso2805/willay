import { HttpErrorResponse } from '@angular/common/http';
import { ageText, stationProblem } from './station-presentation';

describe('station presentation', () => {
  const now = Date.parse('2026-10-27T09:00:00Z');

  it('formats the age of the last measurement', () => {
    expect(ageText('2026-10-27T08:59:48Z', now)).toBe('hace 12 s');
    expect(ageText('2026-10-27T08:57:00Z', now)).toBe('hace 3 min');
    expect(ageText('2026-10-27T06:00:00Z', now)).toBe('hace 3 h');
    expect(ageText('2026-10-25T09:00:00Z', now)).toBe('hace 2 d');
    expect(ageText('2026-10-27T09:00:05Z', now)).toBe('hace 0 s'); // reloj adelantado
  });

  it('explains a duplicate code and passes 422 reasons through', () => {
    expect(stationProblem(new HttpErrorResponse({ status: 409 }))).toContain('ese código');
    const unknownZone = new HttpErrorResponse({
      status: 422,
      error: { detail: [{ loc: ['body', 'zones'], msg: 'zonas desconocidas: [...]' }] },
    });
    expect(stationProblem(unknownZone)).toBe('zonas desconocidas: [...]');
  });
});
