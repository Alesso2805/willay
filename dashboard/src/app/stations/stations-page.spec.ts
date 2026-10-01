import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, input, output, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { FakeLiveEvents, provideFakeLiveEvents } from '../realtime/live-events.testing';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { Zone } from '../zones/zones.api';
import { LonLat, StationMap } from './station-map';
import { StationsPage } from './stations-page';
import { Heartbeat, IssuedKey, Station } from './stations.api';

// Leaflet does not work well in jsdom: a fake map with the same inputs and outputs.
@Component({ selector: 'app-station-map', template: '' })
class FakeStationMap {
  readonly stations = input<Station[]>([]);
  readonly zones = input<Zone[]>([]);
  readonly picking = input(false);
  readonly pending = input<LonLat | null>(null);
  readonly selectedId = input<string | null>(null);
  readonly picked = output<LonLat>();
  static last?: FakeStationMap;
  constructor() {
    FakeStationMap.last = this;
  }
}

const ZONE: Zone = {
  id: 'z1',
  name: 'Chosica',
  description: null,
  risk_level: 'critical',
  population_estimate: null,
  is_active: true,
  geometry: { type: 'MultiPolygon', coordinates: [] },
  created_at: '',
  updated_at: '',
};
const STATION: Station = {
  id: 's1',
  code: 'RIM-TMP-01',
  name: 'Estación sin asignar',
  variable: 'rainfall',
  unit: 'mm',
  location: { type: 'Point', coordinates: [-76.62, -11.88] },
  source: 'simulator',
  expected_interval_s: 10,
  silence_multiplier: 3,
  status: 'active',
  zones: [],
  has_zone: false,
  heartbeat: null,
  api_key_rotated_at: '',
  created_at: '',
};
const URL = `${settings.apiUrl}/v1/stations`;
const ZONES_URL = `${settings.apiUrl}/v1/zones?include_inactive=false`;

function setup(permissions: string[]) {
  const live = new FakeLiveEvents();
  TestBed.configureTestingModule({
    imports: [StationsPage],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: Session, useValue: { me: signal({ permissions }) } },
      provideFakeLiveEvents(live),
    ],
  });
  TestBed.overrideComponent(StationsPage, {
    remove: { imports: [StationMap] },
    add: { imports: [FakeStationMap] },
  });
  const fixture = TestBed.createComponent(StationsPage);
  const http = TestBed.inject(HttpTestingController);
  const element = fixture.nativeElement as HTMLElement;
  const button = (label: string) =>
    [...element.querySelectorAll('button')].find((b) => b.textContent?.includes(label));
  const type = (name: string, value: string) => {
    const field = element.querySelector<HTMLInputElement>(`input[formcontrolname="${name}"]`)!;
    field.value = value;
    field.dispatchEvent(new Event('input'));
  };
  const loaded = (stations: Station[]) => {
    http.expectOne(`${URL}?include_inactive=false`).flush(stations);
    http.expectOne(ZONES_URL).flush([ZONE]);
  };
  return { fixture, http, element, button, type, loaded, live };
}

describe('StationsPage', () => {
  it('has no serious accessibility violations in the list or the form', async () => {
    const { fixture, button, loaded } = setup(['view', 'territory:manage']);
    loaded([STATION]);
    await fixture.whenStable();
    expect(await seriousViolations(fixture.nativeElement)).toEqual([]);

    button('Nueva estación')?.click();
    await fixture.whenStable();
    expect(await seriousViolations(fixture.nativeElement)).toEqual([]);
  });

  it('says it is loading, not that there are no stations, until the list arrives', async () => {
    const { fixture, element, loaded } = setup(['view']);
    await fixture.whenStable();
    expect(element.textContent).toContain('Cargando estaciones…');
    expect(element.textContent).not.toContain('Todavía no hay estaciones.');
    loaded([]);
    await fixture.whenStable();
    expect(element.textContent).toContain('Todavía no hay estaciones.');
  });

  it('marks a station that stopped reporting, with its last value and exact time', async () => {
    const { fixture, element, loaded } = setup(['view']);
    const tenMinutesAgo = new Date(Date.now() - 600_000).toISOString();
    loaded([
      {
        ...STATION,
        has_zone: true,
        heartbeat: { last_seen_at: tenMinutesAgo, last_measured_at: tenMinutesAgo, last_value: 12.3456789 },
      },
    ]);
    await fixture.whenStable();
    expect(element.textContent).toContain('Sin reportar'); // 10 min > 3 × 10 s
    expect(element.textContent).not.toContain('Sin zona');
    expect(element.textContent).toContain('12.3457 mm');
    const age = element.querySelector('time');
    expect(age?.textContent).toContain('hace 10 min');
    expect(age?.getAttribute('title')).toMatch(/^\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/);
  });

  it('updates a station from its live heartbeat, without asking the API again', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    try {
      const { fixture, http, element, loaded, live } = setup(['view']);
      const heartbeat = (value: number): Heartbeat => {
        const now = new Date().toISOString();
        return { last_seen_at: now, last_measured_at: now, last_value: value };
      };
      loaded([{ ...STATION, has_zone: true, heartbeat: heartbeat(1) }]);
      await fixture.whenStable();
      expect(element.textContent).toContain('Reportando');

      vi.advanceTimersByTime(45_000); // the clock moves on its own: 45 s > 3 × 10 s
      await fixture.whenStable();
      expect(element.textContent).toContain('Sin reportar');

      live.heartbeats$.next({ stationId: 's1', heartbeat: heartbeat(42.5) });
      await fixture.whenStable();
      expect(element.textContent).toContain('Reportando');
      expect(element.textContent).toContain('42.5 mm');
      http.verify(); // no polling: the heartbeat came with the event
    } finally {
      vi.useRealTimers();
    }
  });

  it('reloads when the live channel asks for it', async () => {
    const { fixture, element, loaded, live } = setup(['view']);
    loaded([]);
    live.reload$.next(); // on (re)connection, after a possible loss, or polling while down
    loaded([STATION]);
    await fixture.whenStable();
    expect(element.textContent).toContain('RIM-TMP-01');
  });

  it('marks stations without a zone with text, not only on the map', async () => {
    const { fixture, element, loaded } = setup(['view']);
    loaded([STATION]);
    await fixture.whenStable();
    expect(element.textContent).toContain('RIM-TMP-01');
    expect(element.textContent).toContain('Sin zona');
    expect(element.textContent).toContain('Sin lecturas todavía');
  });

  it('hides management actions from users without territory:manage', async () => {
    const { fixture, button, loaded } = setup(['view']);
    loaded([STATION]);
    await fixture.whenStable();
    expect(button('Nueva estación')).toBeUndefined();
    expect(button('Rotar clave')).toBeUndefined();
  });

  it('creates a station from a map click and shows its key once', async () => {
    const { fixture, http, element, button, type, loaded } = setup(['view', 'territory:manage']);
    loaded([]);
    await fixture.whenStable();

    button('Nueva estación')?.click();
    await fixture.whenStable();
    expect(FakeStationMap.last?.picking()).toBe(true);
    FakeStationMap.last?.picked.emit([-76.7654321, -11.9754321]);
    type('code', 'rim-cha-02');
    type('name', 'Chaclacayo 2');
    element.querySelector<HTMLSelectElement>('fieldset select')!.value = 'downstream';
    element.querySelector('fieldset select')!.dispatchEvent(new Event('change'));
    await fixture.whenStable();
    expect(FakeStationMap.last?.pending()).toEqual([-76.765432, -11.975432]);

    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    const request = http.expectOne(URL);
    expect(request.request.body).toMatchObject({
      code: 'rim-cha-02',
      name: 'Chaclacayo 2',
      variable: 'discharge',
      location: { type: 'Point', coordinates: [-76.765432, -11.975432] },
      zones: [{ zone_id: 'z1', position: 'downstream' }],
    });
    const issued: IssuedKey = { station: { ...STATION, code: 'RIM-CHA-02' }, api_key: 's1.secreto' };
    request.flush(issued);
    loaded([]);
    await fixture.whenStable();

    const key = element.querySelector<HTMLInputElement>('input[aria-label="API key"]');
    expect(key?.value).toBe('s1.secreto');
    expect(element.textContent).toContain('no se volverá a mostrar');
    button('Ya la guardé')?.click();
    await fixture.whenStable();
    expect(element.querySelector('input[aria-label="API key"]')).toBeNull();
  });

  it('asks for a location before saving', async () => {
    const { fixture, http, element, button, type, loaded } = setup(['view', 'territory:manage']);
    loaded([]);
    await fixture.whenStable();
    button('Nueva estación')?.click();
    await fixture.whenStable();
    type('code', 'X-01');
    type('name', 'X');

    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    await fixture.whenStable();

    http.expectNone(URL);
    expect(element.querySelector('[role="alert"]')?.textContent).toContain('Falta la ubicación');
  });

  it('rotates a key after confirmation and shows the new one', async () => {
    const { fixture, http, element, button, loaded } = setup(['view', 'territory:manage']);
    loaded([STATION]);
    await fixture.whenStable();
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    button('Rotar clave')?.click();
    http.expectOne(`${URL}/s1/api-key`).flush({ station: STATION, api_key: 's1.nueva' });
    loaded([STATION]);
    await fixture.whenStable();

    expect(element.querySelector<HTMLInputElement>('input[aria-label="API key"]')?.value).toBe('s1.nueva');
  });
});
