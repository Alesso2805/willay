import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { FakeLiveEvents, provideFakeLiveEvents } from '../realtime/live-events.testing';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { FailedReading } from './failed-readings.api';
import { FailedReadingsPage } from './failed-readings-page';

const URL = `${settings.apiUrl}/v1/failed-readings`;
const RAIN: FailedReading = {
  id: 54,
  station_id: 's1',
  station_code: 'RIM-TMP-01',
  station_name: 'Pluviómetro provisional',
  measured_at: '2026-10-02T18:38:47Z',
  value: 7.25,
  unit: 'mm',
  attempts: 5,
  failed_at: '2026-10-02T18:41:47Z',
  last_error: 'regla con parámetros inválidos',
};
const EXPIRED: FailedReading = { ...RAIN, id: 55, value: null, last_error: null };

function setup(permissions = ['view', 'readings:reprocess']) {
  const live = new FakeLiveEvents();
  TestBed.configureTestingModule({
    imports: [FailedReadingsPage],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideFakeLiveEvents(live),
      {
        provide: Session,
        useValue: { me: signal({ permissions, organization_timezone: 'America/Lima' }) },
      },
    ],
  });
  const fixture = TestBed.createComponent(FailedReadingsPage);
  const http = TestBed.inject(HttpTestingController);
  const element = fixture.nativeElement as HTMLElement;
  const text = () => element.textContent ?? '';
  const button = (label: string) =>
    [...element.querySelectorAll('button')].find((b) => b.textContent?.includes(label));
  const listed = async (readings: FailedReading[]) => {
    http.expectOne(URL).flush(readings);
    await fixture.whenStable();
  };
  return { fixture, http, element, text, button, listed, live };
}

describe('FailedReadingsPage', () => {
  beforeEach(() => vi.spyOn(window, 'confirm').mockReturnValue(true));
  afterEach(() => vi.restoreAllMocks());

  it('has no serious accessibility violations', async () => {
    const { element, listed } = setup();
    await listed([RAIN, EXPIRED]);
    expect(await seriousViolations(element)).toEqual([]);
  });

  it('says it is loading, then that every reading was evaluated', async () => {
    const { fixture, text, listed } = setup();
    await fixture.whenStable();
    expect(text()).toContain('Cargando lecturas fallidas…');
    await listed([]);
    expect(text()).toContain('No hay lecturas fallidas: todas se evaluaron.');
    expect(text()).toContain('0 lecturas sin evaluar');
  });

  it('shows the station, the measurement in local time, the attempts and the error', async () => {
    const { element, text, listed } = setup();
    await listed([RAIN, EXPIRED]);
    const row = element.querySelector('tbody tr')!.textContent ?? '';
    expect(row).toContain('RIM-TMP-01');
    expect(row).toContain('7.25 mm');
    expect(row).toContain('02/10/2026 13:38:47'); // Lima
    expect(row).toContain('regla con parámetros inválidos');
    expect(text()).toContain('lectura ya expirada');
    expect(text()).toContain('sin detalle');
  });

  it('reprocesses only the selected readings, after confirming', async () => {
    const { fixture, http, element, text, button, listed } = setup();
    await listed([RAIN, EXPIRED]);
    expect(button('Reprocesar seleccionadas (0)')?.disabled).toBe(true);
    element.querySelector<HTMLInputElement>('tbody input[type="checkbox"]')!.click();
    await fixture.whenStable();

    vi.mocked(window.confirm).mockReturnValueOnce(false);
    button('Reprocesar seleccionadas (1)')?.click();
    http.expectNone(`${URL}/reprocess`);

    button('Reprocesar seleccionadas (1)')?.click();
    const request = http.expectOne({ method: 'POST', url: `${URL}/reprocess` });
    expect(request.request.body).toEqual({ ids: [54] });
    request.flush({ reprocessed: 1 });
    http.expectOne(URL).flush([EXPIRED]);
    await fixture.whenStable();
    expect(text()).toContain('1 lectura devuelta a la cola.');
    expect(button('Reprocesar seleccionadas (0)')).toBeDefined();
  });

  it('selects all, and drops from the selection what is no longer failed', async () => {
    const { fixture, element, button, listed, live, http } = setup();
    await listed([RAIN, EXPIRED]);
    element.querySelector<HTMLInputElement>('label input[type="checkbox"]')!.click();
    await fixture.whenStable();
    expect(button('Reprocesar seleccionadas (2)')).toBeDefined();

    live.failedReadings$.next(); // someone else reprocessed one meanwhile
    http.expectOne(URL).flush([RAIN]);
    await fixture.whenStable();
    expect(button('Reprocesar seleccionadas (1)')).toBeDefined();
  });

  it('explains to a role without access why it sees nothing, without asking the API', async () => {
    const { fixture, http, text } = setup(['view']);
    await fixture.whenStable();
    http.expectNone(URL);
    expect(text()).toContain('Tu rol no permite ver las lecturas fallidas');
  });
});
