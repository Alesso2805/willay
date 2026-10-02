import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, input, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Incident } from '../incidents/incidents.api';
import { FakeLiveEvents, provideFakeLiveEvents } from '../realtime/live-events.testing';
import { Session } from '../session';
import { settings } from '../settings';
import { Station } from '../stations/stations.api';
import { seriousViolations } from '../ui/axe';
import { Zone } from '../zones/zones.api';
import { LiveMap } from './live-map';
import { LiveMapPage } from './live-map-page';
import { StationView, ZoneView } from './live-map-presentation';

// Leaflet does not work well in jsdom: a fake map with the same inputs.
@Component({ selector: 'app-live-map', template: '' })
class FakeLiveMap {
  readonly zones = input<ZoneView[]>([]);
  readonly stations = input<StationView[]>([]);
  static last?: FakeLiveMap;
  constructor() {
    FakeLiveMap.last = this;
  }
}

const INCIDENTS_URL = `${settings.apiUrl}/v1/incidents?status=open&status=acknowledged&limit=500`;
const STATIONS_URL = `${settings.apiUrl}/v1/stations?include_inactive=false`;
const ZONES_URL = `${settings.apiUrl}/v1/zones?include_inactive=false`;

function zone(id: string, name: string): Zone {
  return {
    id,
    name,
    description: null,
    risk_level: 'critical',
    population_estimate: null,
    is_active: true,
    geometry: { type: 'MultiPolygon', coordinates: [] },
    created_at: '',
    updated_at: '',
  };
}

function incident(
  zone_id: string,
  status: Incident['status'],
  rule_type = 'silence',
  station_id = 's1',
): Incident {
  return {
    id: crypto.randomUUID(),
    zone_id,
    zone_name: 'Z',
    station_id,
    station_code: 'RIM-SEU-01',
    rule_type,
    severity: 'critical',
    status,
    current_level: 1,
    opened_at: new Date().toISOString(),
    escalation_exhausted_at: null,
  };
}

function station(id: string, code: string, seenSecondsAgo: number, hasZone = true): Station {
  const seen = new Date(Date.now() - seenSecondsAgo * 1000).toISOString();
  return {
    id,
    code,
    name: `Estación ${code}`,
    variable: 'discharge',
    unit: 'm3/s',
    location: { type: 'Point', coordinates: [-76.7, -11.9] },
    source: 'simulator',
    expected_interval_s: 10,
    silence_multiplier: 3,
    status: 'active',
    zones: [],
    has_zone: hasZone,
    heartbeat: { last_seen_at: seen, last_measured_at: seen, last_value: 83.2 },
    api_key_rotated_at: '',
    created_at: '',
  };
}

function setup() {
  const live = new FakeLiveEvents();
  TestBed.configureTestingModule({
    imports: [LiveMapPage],
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      {
        provide: Session,
        useValue: { me: signal({ permissions: ['view'], organization_timezone: 'America/Lima' }) },
      },
      provideFakeLiveEvents(live),
    ],
  });
  TestBed.overrideComponent(LiveMapPage, {
    remove: { imports: [LiveMap] },
    add: { imports: [FakeLiveMap] },
  });
  const fixture = TestBed.createComponent(LiveMapPage);
  const http = TestBed.inject(HttpTestingController);
  const element = fixture.nativeElement as HTMLElement;
  const text = () => element.textContent?.replace(/\s+/g, ' ') ?? '';
  const loaded = (incidents: Incident[], stations: Station[], zones: Zone[]) => {
    http.expectOne(INCIDENTS_URL).flush(incidents);
    http.expectOne(STATIONS_URL).flush(stations);
    http.expectOne(ZONES_URL).flush(zones);
  };
  return { fixture, http, element, text, loaded, live };
}

const ZONES = [zone('z2', 'Chaclacayo'), zone('z1', 'Chosica')];

describe('LiveMapPage', () => {
  it('shows each zone by its most urgent incident, and its incidents in words', async () => {
    const { fixture, element, text, loaded } = setup();
    loaded([incident('z1', 'acknowledged', 'threshold'), incident('z1', 'open')], [], ZONES);
    await fixture.whenStable();

    expect(FakeLiveMap.last?.zones().map((v) => [v.zone.name, v.state])).toEqual([
      ['Chosica', 'open'], // most urgent first
      ['Chaclacayo', 'calm'],
    ]);
    const cards = [...element.querySelectorAll('#live-zones-title + ul > li')].map(
      (li) => li.textContent?.replace(/\s+/g, ' ') ?? '',
    );
    expect(cards[0]).toContain('Chosica');
    expect(cards[0]).toContain('Incidente abierto');
    expect(cards[0]).toContain('Estación sin reportar · RIM-SEU-01');
    expect(cards[0]).toContain('Valor fuera de límite');
    expect(cards[1]).toContain('Sin incidentes');
    expect(text()).toContain('2 zonas · 1 con incidentes activos');
  });

  it('gives every station a marker state and lists its last value and age', async () => {
    const { fixture, text, loaded } = setup();
    loaded(
      [],
      [station('s1', 'RIM-OK-01', 5), station('s2', 'RIM-SIL-01', 600), station('s3', 'RIM-TMP-01', 5, false)],
      ZONES,
    );
    await fixture.whenStable();

    expect(FakeLiveMap.last?.stations().map((v) => [v.station.code, v.marker])).toEqual([
      ['RIM-SIL-01', 'silent'],
      ['RIM-TMP-01', 'unzoned'],
      ['RIM-OK-01', 'reporting'],
    ]);
    expect(text()).toContain('83.2 m3/s');
    expect(text()).toContain('hace 10 min');
    expect(text()).toContain('Sin zona Reportando'); // the zoneless one also says whether it reports
    expect(text()).toContain('2 de 3 estaciones reportando');
  });

  it('follows live events: a heartbeat updates in place, an incident reloads', async () => {
    const { fixture, http, text, loaded, live } = setup();
    const silent = station('s1', 'RIM-SEU-01', 600);
    loaded([], [silent], ZONES);
    await fixture.whenStable();
    expect(FakeLiveMap.last?.stations()[0].marker).toBe('silent');

    const now = new Date().toISOString();
    live.heartbeats$.next({
      stationId: 's1',
      heartbeat: { last_seen_at: now, last_measured_at: now, last_value: 91.5 },
    });
    await fixture.whenStable();
    expect(FakeLiveMap.last?.stations()[0].marker).toBe('reporting');
    expect(text()).toContain('91.5 m3/s');
    http.verify(); // the heartbeat needed no request

    live.incidents$.next({ incidentId: 'i1', event: 'opened' });
    loaded([incident('z2', 'open')], [silent], ZONES);
    await fixture.whenStable();
    expect(FakeLiveMap.last?.zones()[0]).toMatchObject({ zone: { name: 'Chaclacayo' }, state: 'open' });
    expect(text()).toContain('91.5 m3/s'); // the older REST heartbeat did not undo the live one
  });

  it('shows an acknowledged incident on its station even when the zone stays exhausted', async () => {
    const { fixture, element, loaded } = setup();
    const exhausted = { ...incident('z1', 'open', 'silence', 's2'), escalation_exhausted_at: new Date().toISOString() };
    loaded(
      [exhausted, incident('z1', 'acknowledged', 'threshold', 's1')],
      [station('s1', 'RIM-CHO-01', 600), station('s2', 'RIM-SEU-01', 600)],
      ZONES,
    );
    await fixture.whenStable();

    const chosica = FakeLiveMap.last?.zones().find((v) => v.zone.name === 'Chosica');
    expect(chosica?.state).toBe('exhausted');
    expect(chosica?.summary).toBe('1 con escalamiento agotado · 1 confirmado');
    const badges = Object.fromEntries(
      FakeLiveMap.last?.stations().map((v) => [v.station.code, v.incident]) ?? [],
    );
    expect(badges).toEqual({ 'RIM-CHO-01': 'acknowledged', 'RIM-SEU-01': 'exhausted' });
    const item = [...element.querySelectorAll('#live-stations-title + ul > li')].find((li) =>
      li.textContent?.includes('RIM-CHO-01'),
    );
    expect(item?.textContent).toContain('Incidente confirmado');
  });

  it('says it is loading, not that there is nothing, and has no serious accessibility violations', async () => {
    const { fixture, text, loaded } = setup();
    await fixture.whenStable();
    expect(text()).toContain('Cargando el mapa…');
    loaded([incident('z1', 'open')], [station('s1', 'RIM-SEU-01', 5)], ZONES);
    await fixture.whenStable();
    expect(await seriousViolations(fixture.nativeElement)).toEqual([]);
  });
});
