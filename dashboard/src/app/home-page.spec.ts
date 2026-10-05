import { provideHttpClient } from '@angular/common/http';
import { useLanguage } from './i18n/i18n';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { HomePage } from './home-page';
import { Incident } from './incidents/incidents.api';
import { FakeLiveEvents, provideFakeLiveEvents } from './realtime/live-events.testing';
import { Session } from './session';
import { settings } from './settings';
import { Station } from './stations/stations.api';
import { seriousViolations } from './ui/axe';
import { Zone } from './zones/zones.api';

const ME = {
  email: 'operador@rimac.willay.test',
  organization_name: 'Demo Rímac',
  organization_timezone: 'America/Lima',
  roles: ['operator'],
  permissions: ['view'],
};

function incident(status: Incident['status'], exhausted = false): Incident {
  return {
    id: crypto.randomUUID(),
    zone_id: 'z1',
    zone_name: 'Chosica',
    station_id: 's1',
    station_code: 'RIM-SEU-01',
    rule_type: 'silence',
    severity: 'critical',
    status,
    current_level: 1,
    opened_at: new Date().toISOString(),
    escalation_exhausted_at: exhausted ? new Date().toISOString() : null,
  };
}

function station(seenSecondsAgo: number, hasZone: boolean): Station {
  const seen = new Date(Date.now() - seenSecondsAgo * 1000).toISOString();
  return {
    id: crypto.randomUUID(),
    code: 'RIM-X',
    name: 'X',
    variable: 'discharge',
    unit: 'm3/s',
    location: { type: 'Point', coordinates: [-76.7, -11.9] },
    source: 'simulator',
    expected_interval_s: 10,
    silence_multiplier: 3,
    status: 'active',
    zones: [],
    has_zone: hasZone,
    heartbeat: { last_seen_at: seen, last_measured_at: seen, last_value: 80 },
    api_key_rotated_at: '',
    created_at: '',
  };
}

function zone(risk: Zone['risk_level']): Zone {
  return {
    id: crypto.randomUUID(),
    name: 'Z',
    description: null,
    risk_level: risk,
    population_estimate: null,
    is_active: true,
    geometry: { type: 'MultiPolygon', coordinates: [] },
    created_at: '',
    updated_at: '',
  };
}

const INCIDENTS_URL = `${settings.apiUrl}/v1/incidents?status=open&status=acknowledged&limit=500`;
const STATIONS_URL = `${settings.apiUrl}/v1/stations?include_inactive=false`;
const ZONES_URL = `${settings.apiUrl}/v1/zones?include_inactive=false`;
const DEMO_URL = `${settings.apiUrl}/v1/demo`;
const DEMO_OFF = { available: false, can_run: false, duration_s: 540, timeline: [], run: null };

function setup(permissions: string[]) {
  const live = new FakeLiveEvents();
  TestBed.configureTestingModule({
    imports: [HomePage],
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: Session, useValue: { me: signal({ ...ME, permissions }) } },
      provideFakeLiveEvents(live),
    ],
  });
  const fixture = TestBed.createComponent(HomePage);
  const http = TestBed.inject(HttpTestingController);
  const text = () => (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ') ?? '';
  const loaded = (incidents: Incident[], stations: Station[], zones: Zone[]) => {
    http.expectOne(INCIDENTS_URL).flush(incidents);
    http.expectOne(STATIONS_URL).flush(stations);
    http.expectOne(ZONES_URL).flush(zones);
  };
  return { fixture, http, text, loaded, live };
}

describe('HomePage', () => {
  it('speaks English too', async () => {
    await useLanguage('en');
    const { fixture, text, loaded } = setup(['view']);
    loaded(
      [incident('open', true), incident('acknowledged'), incident('acknowledged')],
      [station(5, true), station(600, false)],
      [zone('critical'), zone('high')],
    );
    await fixture.whenStable();
    expect(text()).toContain('Active incidents');
    expect(text()).toContain('1 unacknowledged · 2 acknowledged · 1 with escalation exhausted');
    expect(text()).toContain('1 of 2');
    expect(text()).toContain('1 not reporting · 1 without a zone');
    expect(text()).toContain('Your account');
  });

  it('sums up active incidents, reporting stations and zones by risk', async () => {
    const { fixture, text, loaded } = setup(['view']);
    loaded(
      [incident('open', true), incident('acknowledged')],
      [station(5, true), station(600, false)],
      [zone('critical'), zone('high')],
    );
    await fixture.whenStable();

    expect(text()).toContain('1 sin confirmar · 1 confirmado · 1 con escalamiento agotado');
    expect(text()).toContain('1 de 2'); // the station silent for 10 min does not count
    expect(text()).toContain('1 sin reportar · 1 sin zona');
    expect(text()).toContain('1 de riesgo crítico · 1 alto');
    expect(await seriousViolations(fixture.nativeElement)).toEqual([]);
  });

  it('follows live events: an incident reloads the summary, a heartbeat updates in place', async () => {
    const { fixture, http, text, loaded, live } = setup(['view']);
    const silent = station(600, true);
    loaded([], [silent], [zone('high')]);
    await fixture.whenStable();
    expect(text()).toContain('0 de 1');

    const now = new Date().toISOString();
    live.heartbeats$.next({
      stationId: silent.id,
      heartbeat: { last_seen_at: now, last_measured_at: now, last_value: 81 },
    });
    await fixture.whenStable();
    expect(text()).toContain('1 de 1');
    // The demo panel asks once it renders, after the summary: not because of the heartbeat.
    for (const request of http.match(DEMO_URL)) request.flush(DEMO_OFF);
    http.verify(); // the heartbeat needed no request

    live.incidents$.next({ incidentId: 'i1', event: 'opened' });
    loaded([incident('open')], [silent], [zone('high')]);
    await fixture.whenStable();
    expect(text()).toContain('1 sin confirmar');
    expect(text()).toContain('1 de 1'); // the older REST heartbeat did not undo the live one
  });

  it('a user without roles gets an explanation and no requests that would be refused', async () => {
    const { fixture, http, text } = setup([]);
    await fixture.whenStable();
    expect(text()).toContain('todavía no tiene un rol en Willay');
    http.verify(); // without the "view" permission, no requests the API would refuse
  });
});
