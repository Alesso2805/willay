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
import { IncidentAlert, IncidentDetail, IncidentReadings } from './incidents.api';

const URL = `${settings.apiUrl}/v1/incidents/i1`;
const ALERTS_URL = `${URL}/alerts`;
const READINGS_URL = `${URL}/readings`;

const READINGS: IncidentReadings = {
  station_code: 'RIM-CHO-01',
  unit: 'm',
  window_start: '2026-10-02T02:31:03Z',
  window_end: '2026-10-02T05:31:03Z',
  source: 'readings',
  readings: [
    { measured_at: '2026-10-02T03:30:53Z', value: 4.2 },
    { measured_at: '2026-10-02T03:31:03Z', value: 4.6 },
  ],
  threshold: { operator: 'gt', value: 3.5 },
};

function alert(overrides: Partial<IncidentAlert>): IncidentAlert {
  return {
    id: crypto.randomUUID(),
    level_order: 1,
    contact_id: 'c1',
    contact_name: 'Óscar Operador',
    channel: 'email',
    status: 'sent',
    attempts: 1,
    sent_at: '2026-10-02T03:31:04Z',
    acknowledged_at: null,
    skipped_reason_code: null,
    skipped_reason: null,
    email: null,
    ...overrides,
  };
}

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
      {
        provide: Session,
        useValue: { me: signal({ organization_timezone: 'America/Lima', permissions: ['view'] }) },
      },
      provideFakeLiveEvents(live),
    ],
  });
  const harness = await RouterTestingHarness.create();
  await harness.navigateByUrl(`/incidentes/${id}`, IncidentDetailPage);
  const http = TestBed.inject(HttpTestingController);
  const element = harness.routeNativeElement as HTMLElement;
  const text = () => element.textContent?.replace(/\s+/g, ' ') ?? '';
  const stable = () => harness.fixture.whenStable();
  /** Answers the detail, its alerts and its readings, which the page asks for together. */
  const respond = async (
    detail: IncidentDetail = DETAIL,
    alerts: IncidentAlert[] = [],
    readings: IncidentReadings = READINGS,
  ) => {
    http.expectOne(URL).flush(detail);
    http.expectOne(ALERTS_URL).flush(alerts);
    http.expectOne(READINGS_URL).flush(readings);
    await stable();
  };
  return { http, element, text, stable, live, respond };
}

describe('IncidentDetailPage', () => {
  it('shows the summary and the timeline in words, in the organization\'s time', async () => {
    const { element, text, respond } = await setup();
    expect(text()).toContain('Cargando incidente…');
    await respond();

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
    const { http, live, respond } = await setup();
    await respond({ ...DETAIL, timeline: [] });

    live.incidents$.next({ incidentId: 'other', event: 'opened' });
    http.expectNone(URL);

    live.incidents$.next({ incidentId: 'i1', event: 'resolved' });
    await respond({ ...DETAIL, status: 'resolved', resolved_at: '2026-10-02T06:00:00Z', resolution: 'false_alarm' });

    live.reload$.next();
    await respond();
  });

  it('lists the alerts by level, with the email only when the API sends it', async () => {
    const { element, respond } = await setup();
    await respond(DETAIL, [
      alert({ email: 'operador@rimac.willay.test' }),
      alert({ level_order: 2, contact_name: 'Rosa Brigada', channel: 'telegram', status: 'skipped', sent_at: null, skipped_reason_code: 'no_telegram' }),
      alert({ level_order: 3, contact_name: 'Carmen Jefatura COE', status: 'acknowledged', acknowledged_at: '2026-10-02T05:30:01Z' }),
    ]);

    const section = element.querySelector('section[aria-labelledby="alerts-title"]') as HTMLElement;
    // From md up, a table: one row per alert, each fact in its column.
    const table = section.querySelector('table') as HTMLTableElement;
    expect([...table.querySelectorAll('th')].map((th) => th.textContent?.trim())).toEqual([
      'Nivel',
      'Destinatario',
      'Canal',
      'Estado',
      'Cuándo',
      'Motivo',
    ]);
    // A cell with paragraphs (name and email) shows them one below the other.
    const cell = (td: Element) => {
      const parts = [...td.querySelectorAll('p')].map((p) => p.textContent?.trim());
      return parts.length > 0 ? parts.join(' / ') : td.textContent?.replace(/\s+/g, ' ').trim();
    };
    const rows = [...table.querySelectorAll('tbody tr')].map((tr) =>
      [...tr.querySelectorAll('td')].map(cell),
    );
    expect(rows[0]).toEqual([
      '1',
      'Óscar Operador / operador@rimac.willay.test',
      'Correo',
      'Enviada',
      'Enviada el 01/10/2026 22:31',
      '—',
    ]);
    expect(rows[1]).toEqual(['2', 'Rosa Brigada', 'Telegram', 'Omitida', '—', 'el contacto no vinculó Telegram']);
    expect(rows[2][4]).toBe('Confirmó el 02/10/2026 00:30');

    // Narrower, the same alerts as cards grouped by level.
    const levels = [...section.querySelectorAll('h3')].map((h) => h.textContent?.trim());
    expect(levels).toEqual(['Nivel 1', 'Nivel 2', 'Nivel 3']);
    const cards = [...section.querySelectorAll('li')].map((li) => li.textContent?.replace(/\s+/g, ' ').trim());
    expect(cards[1]).toContain('Rosa Brigada · Telegram');
    expect(cards[1]).toContain('el contacto no vinculó Telegram');
    expect(cards[1]).not.toContain('@');
  });

  it('draws the readings with the threshold and the opening, and says when they are the copy', async () => {
    const { element, respond } = await setup();
    await respond(DETAIL, [], { ...READINGS, source: 'evidence' });
    const chart = element.querySelector('section[aria-labelledby="chart-title"]') as HTMLElement;
    expect(chart.textContent).toContain('Las lecturas de este periodo ya expiraron');
    expect(chart.querySelector('svg desc')?.textContent).toContain('2 lecturas de RIM-CHO-01');
    expect(chart.textContent).toContain('Umbral: más de 3.5 m');
    expect(chart.textContent).toContain('Apertura');
    expect(chart.textContent).toContain('Confirmación');
  });

  it('says when an incident raised no alerts', async () => {
    const { text, respond } = await setup();
    await respond(DETAIL, []);
    expect(text()).toContain('Este incidente no generó alertas.');
  });

  it('says when the incident does not exist, or is another organization\'s', async () => {
    const { http, text, stable } = await setup('nope');
    http.expectOne(`${settings.apiUrl}/v1/incidents/nope`).flush({ detail: 'x' }, { status: 404, statusText: 'Not Found' });
    await stable();
    expect(text()).toContain('No encontramos ese incidente');
  });

  it('keeps what it shows when a reload fails', async () => {
    const { http, text, stable, live, respond } = await setup();
    await respond();
    live.reload$.next();
    http.expectOne(URL).flush(null, { status: 503, statusText: 'Unavailable' });
    await stable();
    expect(text()).toContain('Valor fuera de límite');
    expect(text()).not.toContain('No se pudo cargar');
  });
});
