import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { FakeLiveEvents, provideFakeLiveEvents } from '../realtime/live-events.testing';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { IncidentDetailPage } from './incident-detail-page';
import { IncidentDetail } from './incidents.api';

const URL = `${settings.apiUrl}/v1/incidents/i1`;

const DETAIL: IncidentDetail = {
  id: 'i1',
  zone_id: 'z1',
  zone_name: 'Chosica',
  station_id: 's1',
  station_code: 'RIM-CHO-01',
  rule_type: 'threshold',
  severity: 'warning',
  status: 'acknowledged',
  current_level: 3,
  opened_at: '2026-10-02T03:31:03Z',
  escalation_exhausted_at: '2026-10-02T03:41:11Z',
  trigger_value: 4.6,
  acknowledged_at: '2026-10-02T05:30:01Z',
  resolved_at: null,
  resolution: null,
  timeline: [
    {
      id: 1,
      occurred_at: '2026-10-02T03:31:03Z',
      event_type: 'opened',
      actor_type: 'system',
      actor_id: null,
      actor_name: null,
      contact_name: null,
      payload: { rule_type: 'threshold', rule_params: { operator: 'gt', value: 3.5, consecutive: 2 }, trigger_value: 4.6 },
    },
    {
      id: 2,
      occurred_at: '2026-10-02T03:31:04Z',
      event_type: 'alert_sent',
      actor_type: 'system',
      actor_id: null,
      actor_name: null,
      contact_name: 'Óscar Operador',
      payload: { channel: 'email', level_order: 1 },
    },
    {
      id: 3,
      occurred_at: '2026-10-02T05:30:01Z',
      event_type: 'acknowledged',
      actor_type: 'contact',
      actor_id: 'c1',
      actor_name: 'Rosa Brigada',
      contact_name: null,
      payload: {},
    },
  ],
};

async function setup(id = 'i1') {
  const live = new FakeLiveEvents();
  TestBed.configureTestingModule({
    providers: [
      provideRouter([{ path: 'incidentes/:id', component: IncidentDetailPage }]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: Session, useValue: { me: signal({ organization_timezone: 'America/Lima' }) } },
      provideFakeLiveEvents(live),
    ],
  });
  const harness = await RouterTestingHarness.create();
  await harness.navigateByUrl(`/incidentes/${id}`, IncidentDetailPage);
  const http = TestBed.inject(HttpTestingController);
  const element = harness.routeNativeElement as HTMLElement;
  const text = () => element.textContent?.replace(/\s+/g, ' ') ?? '';
  const stable = () => harness.fixture.whenStable();
  return { http, element, text, stable, live };
}

describe('IncidentDetailPage', () => {
  it('shows the summary and the timeline in words, in the organization\'s time', async () => {
    const { http, element, text, stable } = await setup();
    expect(text()).toContain('Cargando incidente…');
    http.expectOne(URL).flush(DETAIL);
    await stable();

    expect(element.querySelector('h1')?.textContent).toContain('Valor fuera de límite · RIM-CHO-01');
    expect(text()).toContain('Chosica · abierto el 01/10/2026 22:31');
    expect(text()).toContain('Confirmado');
    expect(text()).toContain('Advertencia');
    expect(text()).toContain('3 · agotado');
    expect(text()).toContain('02/10/2026 00:30 por Rosa Brigada');
    // Each line of an event, as the screen shows them one below the other.
    const lines = [...element.querySelectorAll('ol > li')].map((li) =>
      [...li.querySelectorAll('p, time')].map((part) => part.textContent?.trim()).join(' | '),
    );
    expect(lines).toEqual([
      'Se abrió el incidente | Regla: más de 3.5 en 2 lecturas seguidas · valor 4.6 | 01/10/2026 22:31:03',
      'Alerta enviada a Óscar Operador por correo | nivel 1 | 01/10/2026 22:31:04',
      'Confirmado por Rosa Brigada | Desde su alerta | 02/10/2026 00:30:01',
    ]);
    expect(await seriousViolations(element)).toEqual([]);
  });

  it('reloads with its own live events and reconnections, not with other incidents', async () => {
    const { http, stable, live } = await setup();
    http.expectOne(URL).flush({ ...DETAIL, timeline: [] });
    await stable();

    live.incidents$.next({ incidentId: 'other', event: 'opened' });
    http.expectNone(URL);

    live.incidents$.next({ incidentId: 'i1', event: 'resolved' });
    http.expectOne(URL).flush({ ...DETAIL, status: 'resolved', resolved_at: '2026-10-02T06:00:00Z', resolution: 'false_alarm' });
    await stable();

    live.reload$.next();
    http.expectOne(URL).flush(DETAIL);
  });

  it('says when the incident does not exist, or is another organization\'s', async () => {
    const { http, text, stable } = await setup('nope');
    http.expectOne(`${settings.apiUrl}/v1/incidents/nope`).flush({ detail: 'x' }, { status: 404, statusText: 'Not Found' });
    await stable();
    expect(text()).toContain('No encontramos ese incidente');
  });

  it('keeps what it shows when a reload fails', async () => {
    const { http, text, stable, live } = await setup();
    http.expectOne(URL).flush(DETAIL);
    await stable();
    live.reload$.next();
    http.expectOne(URL).flush(null, { status: 503, statusText: 'Unavailable' });
    await stable();
    expect(text()).toContain('Valor fuera de límite');
    expect(text()).not.toContain('No se pudo cargar');
  });
});
