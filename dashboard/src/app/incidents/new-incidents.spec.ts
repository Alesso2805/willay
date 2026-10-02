import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { FakeLiveEvents, provideFakeLiveEvents } from '../realtime/live-events.testing';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { Incident } from './incidents.api';
import { NewIncidents } from './new-incidents';

const INCIDENT: Incident = {
  id: 'i1',
  zone_id: 'z1',
  zone_name: 'Chosica',
  station_id: 's1',
  station_code: 'RIM-SEU-01',
  rule_type: 'silence',
  severity: 'critical',
  status: 'open',
  current_level: 1,
  opened_at: '2026-10-02T02:40:39Z',
  escalation_exhausted_at: null,
};

function setup() {
  const live = new FakeLiveEvents();
  TestBed.configureTestingModule({
    imports: [NewIncidents],
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: Session, useValue: { me: signal({ organization_timezone: 'America/Lima' }) } },
      provideFakeLiveEvents(live),
    ],
  });
  const fixture = TestBed.createComponent(NewIncidents);
  const http = TestBed.inject(HttpTestingController);
  const element = fixture.nativeElement as HTMLElement;
  const region = () => element.querySelector('[aria-live="assertive"]');
  const text = () => region()?.textContent?.replace(/\s+/g, ' ').trim() ?? '';
  const opened = (incident: Incident) => {
    live.incidents$.next({ incidentId: incident.id, event: 'opened' });
    http.expectOne(`${settings.apiUrl}/v1/incidents/${incident.id}`).flush(incident);
  };
  return { fixture, http, element, region, text, opened, live };
}

describe('NewIncidents', () => {
  it('announces a new incident in a live region that was already there', async () => {
    const { fixture, element, region, text, opened } = setup();
    await fixture.whenStable();
    expect(region()).not.toBeNull(); // present before anything happens

    opened(INCIDENT);
    await fixture.whenStable();
    expect(text()).toContain(
      'Nuevo incidente en Chosica: Estación sin reportar · RIM-SEU-01 · 01/10/2026 21:40',
    );
    expect(text()).toContain('Crítico');
    expect(element.querySelector('a')?.getAttribute('href')).toBe('/incidentes/i1');
    expect(await seriousViolations(element)).toEqual([]);
  });

  it('only announces openings, each one once, newest first', async () => {
    const { fixture, http, text, opened, live } = setup();
    live.incidents$.next({ incidentId: 'i1', event: 'alert_sent' });
    live.incidents$.next({ incidentId: 'i1', event: 'acknowledged' });
    http.expectNone(`${settings.apiUrl}/v1/incidents/i1`);

    opened(INCIDENT);
    opened({ ...INCIDENT, id: 'i2', zone_name: 'Chaclacayo' });
    opened(INCIDENT); // e.g. a resync replayed it
    await fixture.whenStable();
    expect(text().match(/Nuevo incidente/g)).toHaveLength(2);
    expect(text().indexOf('Chaclacayo')).toBeLessThan(text().indexOf('Chosica'));
  });

  it('closes a notice without touching the others', async () => {
    const { fixture, element, text, opened } = setup();
    opened(INCIDENT);
    opened({ ...INCIDENT, id: 'i2', zone_name: 'Chaclacayo' });
    await fixture.whenStable();

    element.querySelector<HTMLButtonElement>('button[aria-label$="en Chosica"]')?.click();
    await fixture.whenStable();
    expect(text()).not.toContain('Chosica');
    expect(text()).toContain('Chaclacayo');
  });

  it('still announces the incident when its details cannot be loaded', async () => {
    const { fixture, http, text, live } = setup();
    live.incidents$.next({ incidentId: 'i1', event: 'opened' });
    http
      .expectOne(`${settings.apiUrl}/v1/incidents/i1`)
      .flush(null, { status: 503, statusText: 'Unavailable' });
    await fixture.whenStable();
    expect(text()).toContain('Se abrió un nuevo incidente.');
  });
});
