import { HttpErrorResponse } from '@angular/common/http';
import { useLanguage } from '../i18n/i18n';
import { problemPoint, riskLabel, saveProblem } from './zone-presentation';

function apiError(status: number, detail?: unknown): HttpErrorResponse {
  return new HttpErrorResponse({ status, error: detail === undefined ? null : { detail } });
}

describe('zone presentation', () => {
  it('explains problems and names risk levels in English too', async () => {
    await useLanguage('en');
    const problem = saveProblem(apiError(422, [{ msg: 'Self-intersection[-76.65 -11.95]' }]));
    expect(problem.message).toBe('The polygon crosses itself. Fix the point marked on the map.');
    expect(saveProblem(apiError(403)).message).toBe('Your role does not allow managing zones.');
    expect(riskLabel('critical')).toBe('Critical');
  });

  it('extracts the point PostGIS reports for a self-intersection', () => {
    expect(problemPoint('Self-intersection[-76.65 -11.95]')).toEqual([-76.65, -11.95]);
    expect(problemPoint('Too few points[1 0]')).toEqual([1, 0]);
    expect(problemPoint('el anillo no está cerrado')).toBeNull();
  });

  it('turns a self-intersection 422 into a message and a map point', () => {
    const problem = saveProblem(
      apiError(422, [{ loc: ['body', 'geometry'], msg: 'Self-intersection[-76.65 -11.95]' }]),
    );
    expect(problem.message).toContain('se cruza consigo mismo');
    expect(problem.point).toEqual([-76.65, -11.95]);
  });

  it('shows other 422 reasons as they come from the API', () => {
    const problem = saveProblem(apiError(422, [{ msg: 'el anillo no está cerrado' }]));
    expect(problem).toEqual({ message: 'el anillo no está cerrado', point: null });
  });

  it('explains a 403 and falls back to a generic message otherwise', () => {
    expect(saveProblem(apiError(403)).message).toContain('Tu rol no permite');
    expect(saveProblem(apiError(500)).message).toContain('Intenta de nuevo');
    expect(saveProblem(new Error('x')).message).toContain('No se pudo guardar');
  });
});
