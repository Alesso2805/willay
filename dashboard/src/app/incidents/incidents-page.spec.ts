import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { FakeLiveEvents, provideFakeLiveEvents } from '../realtime/live-events.testing';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { INBOX_LIMIT, IncidentsPage } from './incidents-page';
import { Incident } from './incidents.api';

const URL = `${settings.apiUrl}/v1/incidents`;

function incident(overrides: Partial<Incident> = {}): Incident {
  return {
    id: crypto.randomUUID(),
    zone_id: 'z1',
    zone_name: 'Chosica',
    station_id: 's1',
    station_code: 'RIM-SEU-01',
    rule_type: 'silence',
    severity: 'critical',
    status: 'open',
    current_level: 2,
    opened_at: '2026-10-02T02:40:39Z',
    escalation_exhausted_at: null,
    ...overrides,
  };
}

async function setup(url = '/incidentes') {
  const live = new FakeLiveEvents();
  TestBed.configureTestingModule({
    providers: [
      provideRouter([{ path: 'incidentes', component: IncidentsPage }]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: Session, useValue: { me: signal({ organization_timezone: 'America/Lima' }) } },
      provideFakeLiveEvents(live),
    ],
  });
  const harness = await RouterTestingHarness.create();
  await harness.navigateByUrl(url, IncidentsPage);
  const http = TestBed.inject(HttpTestingController);
  const element = harness.routeNativeElement as HTMLElement;
  const text = () => element.textContent?.replace(/\s+/g, ' ') ?? '';
  const stable = () => harness.fixture.whenStable();
  /** The pending list request: its filters, so the test can flush it. */
  const request = async () => {
    await stable();
    const pending = http.expectOne((r) => r.url === URL);
    const params = pending.request.params;
    return {
      statuses: params.getAll('status'),
      severities: params.getAll('severity') ?? [],
      limit: params.get('limit'),
      flush: async (incidents: Incident[]) => {
        pending.flush(incidents);
        await stable();
      },
    };
  };
  const checkbox = (label: string) =>
    [...element.querySelectorAll('label')]
      .find((l) => l.textContent?.trim() === label)
      ?.querySelector('input') as HTMLInputElement;
  return { http, element, text, request, checkbox, live, stable };
}

describe('IncidentsPage', () => {
  it('opens with open and acknowledged incidents and everything the operator needs', async () => {
    const { element, text, request } = await setup();
    const pending = await request();
    expect(pending.statuses).toEqual(['open', 'acknowledged']);
    expect(pending.severities).toEqual([]);
    expect(pending.limit).toBe(String(INBOX_LIMIT));

    await pending.flush([
      incident({ escalation_exhausted_at: '2026-10-02T02:45:00Z' }),
      incident({ status: 'acknowledged', rule_type: 'threshold', severity: 'warning', station_code: 'RIM-CHO-01' }),
    ]);
    expect(text()).toContain('2 incidentes · 1 con escalamiento agotado');
    const cards = [...element.querySelectorAll('li')];
    expect(cards[0].textContent).toContain('Escalamiento agotado');
    expect(cards[0].classList).toContain('border-l-4'); // highlighted, not only by its badge
    expect(cards[0].textContent?.replace(/\s+/g, ' ')).toContain('Estación sin reportar · RIM-SEU-01');
    expect(cards[0].textContent).toContain('Chosica');
    expect(cards[0].textContent).toContain('Nivel 2');
    expect(cards[0].textContent).toContain('01/10/2026 21:40'); // the organization's time
    expect(cards[1].textContent).toContain('Confirmado');
    expect(cards[1].textContent).toContain('Advertencia');
    expect(cards[1].classList).not.toContain('border-l-4');
    expect(await seriousViolations(element)).toEqual([]);
  });

  it('reads its filters from the URL', async () => {
    const { request, checkbox } = await setup('/incidentes?estado=resolved&severidad=critical&severidad=x');
    const pending = await request();
    expect(pending.statuses).toEqual(['resolved']);
    expect(pending.severities).toEqual(['critical']);
    await pending.flush([]);
    expect(checkbox('Resuelto').checked).toBe(true);
    expect(checkbox('Abierto').checked).toBe(false);
    expect(checkbox('Crítico').checked).toBe(true);
  });

  it('puts each filter change in the URL and reloads with it', async () => {
    const { request, checkbox } = await setup();
    await (await request()).flush([]);

    checkbox('Resuelto').click();
    let pending = await request();
    expect(pending.statuses).toEqual(['open', 'acknowledged', 'resolved']);
    expect(TestBed.inject(Router).url).toBe(
      '/incidentes?estado=open&estado=acknowledged&estado=resolved',
    );
    await pending.flush([]);

    checkbox('Crítico').click();
    pending = await request();
    expect(pending.severities).toEqual(['critical']);
    expect(TestBed.inject(Router).url).toContain('severidad=critical');
    await pending.flush([]);
  });

  it('keeps at least one status checked', async () => {
    const { request, checkbox } = await setup('/incidentes?estado=open');
    await (await request()).flush([]);
    expect(checkbox('Abierto').disabled).toBe(true);
    expect(checkbox('Confirmado').disabled).toBe(false);
  });

  it('reloads on live events, keeping the filters', async () => {
    const { request, live } = await setup('/incidentes?severidad=warning');
    await (await request()).flush([]);

    live.incidents$.next({ incidentId: 'i1', event: 'acknowledged' });
    let pending = await request();
    expect(pending.severities).toEqual(['warning']);
    await pending.flush([incident({ severity: 'warning' })]);

    live.reload$.next();
    pending = await request();
    await pending.flush([]);
  });

  it('says that nothing matches, not that something failed, and announces it', async () => {
    const { element, text, request } = await setup();
    await (await request()).flush([]);
    expect(text()).toContain('No hay incidentes con estos filtros.');
    expect(text()).not.toContain('No se pudieron cargar');
    expect(element.querySelector('[role="status"]')?.textContent).toContain(
      'No hay incidentes con estos filtros.',
    );
  });
});
