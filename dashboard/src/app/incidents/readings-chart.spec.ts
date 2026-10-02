import { TestBed } from '@angular/core/testing';
import { seriousViolations } from '../ui/axe';
import { IncidentReadings } from './incidents.api';
import { ReadingsChart } from './readings-chart';

const DATA: IncidentReadings = {
  station_code: 'RIM-CHO-01',
  unit: 'm',
  window_start: '2026-10-02T02:31:00Z',
  window_end: '2026-10-02T05:31:00Z',
  source: 'readings',
  readings: [
    { measured_at: '2026-10-02T03:30:00Z', value: 2.0 },
    { measured_at: '2026-10-02T03:30:10Z', value: 4.2 },
    { measured_at: '2026-10-02T03:30:20Z', value: 4.6 },
  ],
  threshold: { operator: 'gt', value: 3.5 },
};

async function render(data: IncidentReadings = DATA) {
  const fixture = TestBed.createComponent(ReadingsChart);
  fixture.componentRef.setInput('data', data);
  fixture.componentRef.setInput('timezone', 'America/Lima');
  fixture.componentRef.setInput('marks', [{ at: '2026-10-02T03:30:20Z', label: 'Apertura' }]);
  await fixture.whenStable();
  const element = fixture.nativeElement as HTMLElement;
  return { fixture, element };
}

describe('ReadingsChart', () => {
  it('draws the line, the threshold and the marks, and describes them in words', async () => {
    const { element } = await render();
    expect(element.querySelectorAll('svg path')).toHaveLength(1);
    expect(element.querySelectorAll('svg circle')).toHaveLength(3); // few points: dots too
    expect(element.textContent).toContain('Umbral: más de 3.5 m');
    expect(element.textContent).toContain('Apertura');
    expect(element.querySelector('svg')?.getAttribute('role')).toBe('img');
    expect(element.querySelector('desc')?.textContent).toBe(
      '3 lecturas de RIM-CHO-01 a las 22:30; mínimo 2 y máximo 4.6 m; umbral más de 3.5 m.',
    );
    // The time axis is in the organization's time zone.
    const times = [...element.querySelectorAll('svg text')].map((t) => t.textContent?.trim());
    expect(times).toContain('22:30');
    expect(await seriousViolations(element)).toEqual([]);
  });

  it('fits the time axis to the readings, not to the whole three-hour window', async () => {
    const minute = (m: number) => new Date(Date.parse('2026-10-02T03:20:00Z') + m * 60_000).toISOString();
    const { element } = await render({
      ...DATA,
      readings: [0, 5, 10].map((m) => ({ measured_at: minute(m), value: 2 + m / 10 })),
    });
    const x = [...element.querySelectorAll('svg circle')].map((c) => Number(c.getAttribute('cx')));
    // Ten minutes of readings in a three-hour window still spread across most of the plot.
    expect(x[x.length - 1] - x[0]).toBeGreaterThan(300);
  });

  it('keeps an hour label on the axis for a burst of a few seconds', async () => {
    const { element } = await render(); // three readings within 20 s
    const labels = [...element.querySelectorAll('svg text')].map((t) => t.textContent?.trim() ?? '');
    expect(labels.filter((l) => /^\d{2}:\d{2}$/.test(l)).length).toBeGreaterThan(0);
  });

  it('breaks the line where the station stopped reporting', async () => {
    const at = (minutes: number, value: number) => ({
      measured_at: new Date(Date.parse('2026-10-02T03:00:00Z') + minutes * 60_000).toISOString(),
      value,
    });
    const { element } = await render({
      ...DATA,
      threshold: null,
      readings: [at(0, 1), at(1, 1), at(2, 1), at(3, 1), at(40, 2), at(41, 2), at(42, 2)],
    });
    expect(element.querySelectorAll('svg path')).toHaveLength(2);
    expect(element.textContent).not.toContain('Umbral');
  });

  it('shows every reading as a table on request', async () => {
    const { fixture, element } = await render();
    const button = element.querySelector('figcaption button') as HTMLButtonElement;
    expect(button.getAttribute('aria-expanded')).toBe('false');
    button.click();
    await fixture.whenStable();
    expect(button.getAttribute('aria-expanded')).toBe('true');
    const rows = [...element.querySelectorAll('tbody tr')].map((tr) =>
      [...tr.querySelectorAll('td')].map((td) => td.textContent?.trim()).join(' | '),
    );
    expect(rows).toEqual([
      '01/10/2026 22:30:00 | 2',
      '01/10/2026 22:30:10 | 4.2',
      '01/10/2026 22:30:20 | 4.6',
    ]);
    expect(await seriousViolations(element)).toEqual([]);
  });

  it('says so when the window has no readings', async () => {
    const { element } = await render({ ...DATA, readings: [], threshold: null });
    expect(element.querySelector('desc')?.textContent).toContain('Sin lecturas de RIM-CHO-01');
  });
});
