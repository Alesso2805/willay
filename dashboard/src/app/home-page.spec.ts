import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { HomePage } from './home-page';
import { Incident } from './incidents/incidents.api';
import { Session } from './session';
import { settings } from './settings';
import { Station } from './stations/stations.api';
import { seriousViolations } from './ui/axe';
import { Zone } from './zones/zones.api';

const ME = {
  email: 'operador@rimac.vigia.test',
  organization_name: 'Demo Rímac',
  organization_timezone: 'America/Lima',
  roles: ['operator'],
  permissions: ['view'],
};

function incident(status: Incident['status'], exhausted = false): Incident {
  return {
    id: crypto.randomUUID(),
    zone_name: 'Chosica',
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

function setup(permissions: string[]) {
  TestBed.configureTestingModule({
    imports: [HomePage],
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: Session, useValue: { me: signal({ ...ME, permissions }) } },
    ],
  });
  const fixture = TestBed.createComponent(HomePage);
  const http = TestBed.inject(HttpTestingController);
  const text = () => (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ') ?? '';
  return { fixture, http, text };
}

describe('HomePage', () => {
  it('sums up active incidents, reporting stations and zones by risk', async () => {
    const { fixture, http, text } = setup(['view']);
    http
      .expectOne(`${settings.apiUrl}/v1/incidents?status=open&status=acknowledged&limit=500`)
      .flush([incident('open', true), incident('acknowledged')]);
    http
      .expectOne(`${settings.apiUrl}/v1/stations?include_inactive=false`)
      .flush([station(5, true), station(600, false)]);
    http
      .expectOne(`${settings.apiUrl}/v1/zones?include_inactive=false`)
      .flush([zone('critical'), zone('high')]);
    await fixture.whenStable();

    expect(text()).toContain('1 sin confirmar · 1 confirmados · 1 con escalamiento agotado');
    expect(text()).toContain('1 de 2'); // the station silent for 10 min does not count
    expect(text()).toContain('1 sin reportar · 1 sin zona');
    expect(text()).toContain('1 de riesgo crítico · 1 alto');
    expect(await seriousViolations(fixture.nativeElement)).toEqual([]);
  });

  it('a user without roles gets an explanation and no requests that would be refused', async () => {
    const { fixture, http, text } = setup([]);
    await fixture.whenStable();
    expect(text()).toContain('todavía no tiene un rol en Vigía');
    http.verify(); // without the "view" permission, no requests the API would refuse
  });
});
