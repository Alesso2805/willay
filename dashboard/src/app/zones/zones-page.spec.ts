import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, input, output, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { DrawnGeometry, MapMode, ZoneMap } from './zone-map';
import { ZonesPage } from './zones-page';
import { Position, Zone } from './zones.api';

// Leaflet no funciona bien en jsdom: el mapa real se reemplaza por uno falso que expone
// las mismas entradas y salidas. Aquí se prueba la lógica de la página, no Leaflet.
@Component({ selector: 'app-zone-map', template: '' })
class FakeZoneMap {
  readonly zones = input<Zone[]>([]);
  readonly mode = input<MapMode>({ kind: 'view' });
  readonly problem = input<Position | null>(null);
  readonly geometryChange = output<DrawnGeometry>();
  static last?: FakeZoneMap;
  constructor() {
    FakeZoneMap.last = this;
  }
}

const RING: Position[] = [
  [-76.7, -11.9],
  [-76.6, -11.9],
  [-76.6, -12.0],
  [-76.7, -11.9],
];
const ZONE: Zone = {
  id: 'z1',
  name: 'Chosica',
  description: null,
  risk_level: 'critical',
  population_estimate: 45000,
  is_active: true,
  geometry: { type: 'MultiPolygon', coordinates: [[RING]] },
  created_at: '2026-10-26T09:00:00Z',
  updated_at: '2026-10-26T09:00:00Z',
};
const URL = `${settings.apiUrl}/v1/zones`;

function setup(permissions: string[]) {
  const me = signal({ permissions });
  TestBed.configureTestingModule({
    imports: [ZonesPage],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: Session, useValue: { me } },
    ],
  });
  TestBed.overrideComponent(ZonesPage, {
    remove: { imports: [ZoneMap] },
    add: { imports: [FakeZoneMap] },
  });
  const fixture = TestBed.createComponent(ZonesPage);
  const http = TestBed.inject(HttpTestingController);
  const element = fixture.nativeElement as HTMLElement;
  const button = (label: string) =>
    [...element.querySelectorAll('button')].find((b) => b.textContent?.includes(label));
  return { fixture, http, element, button };
}

describe('ZonesPage', () => {
  it('lists zones with their risk level as text, not only as a color', async () => {
    const { fixture, http, element } = setup(['view']);
    http.expectOne(`${URL}?include_inactive=false`).flush([ZONE]);
    await fixture.whenStable();
    expect(element.textContent).toContain('Chosica');
    expect(element.textContent?.replace(/\s+/g, ' ')).toContain('Riesgo: Crítico');
    expect(FakeZoneMap.last?.zones()).toEqual([ZONE]);
  });

  it('has no serious accessibility violations in the list, the form or an error', async () => {
    const { fixture, http, button } = setup(['view', 'territory:manage']);
    http.expectOne(`${URL}?include_inactive=false`).flush([ZONE]);
    await fixture.whenStable();
    expect(await seriousViolations(fixture.nativeElement)).toEqual([]);

    button('Nueva zona')?.click();
    await fixture.whenStable();
    expect(await seriousViolations(fixture.nativeElement)).toEqual([]);

    button('Cancelar')?.click();
    // Una recarga que falla: el aviso de error también tiene que ser accesible.
    (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>('input[type="checkbox"]')?.click();
    http
      .expectOne(`${URL}?include_inactive=true`)
      .flush({ detail: 'x' }, { status: 500, statusText: 'Server Error' });
    await fixture.whenStable();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('No se pudieron cargar las zonas.');
    expect(await seriousViolations(fixture.nativeElement)).toEqual([]);
  });

  it('hides management actions from users without territory:manage', async () => {
    const { fixture, http, button } = setup(['view']);
    http.expectOne(`${URL}?include_inactive=false`).flush([ZONE]);
    await fixture.whenStable();
    expect(button('Nueva zona')).toBeUndefined();
    expect(button('Editar')).toBeUndefined();
  });

  it('creates a zone from the drawn polygon', async () => {
    const { fixture, http, element, button } = setup(['view', 'territory:manage']);
    http.expectOne(`${URL}?include_inactive=false`).flush([]);
    await fixture.whenStable();

    button('Nueva zona')?.click();
    await fixture.whenStable();
    expect(FakeZoneMap.last?.mode()).toEqual({ kind: 'draw' });

    FakeZoneMap.last?.geometryChange.emit({ type: 'Polygon', coordinates: [RING] });
    const name = element.querySelector<HTMLInputElement>('input[formcontrolname="name"]');
    name!.value = 'Quirio';
    name!.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    expect(element.textContent).toContain('3 vértices');

    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    const request = http.expectOne(URL);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toMatchObject({
      name: 'Quirio',
      risk_level: 'high',
      geometry: { type: 'Polygon', coordinates: [RING] },
      is_active: true,
    });
    request.flush({ ...ZONE, id: 'z2', name: 'Quirio' });
    http.expectOne(`${URL}?include_inactive=false`).flush([]);
    await fixture.whenStable();
    expect(element.textContent).toContain('Zona «Quirio» guardada');
    expect(FakeZoneMap.last?.mode()).toEqual({ kind: 'view' });
  });

  it('marks the self-intersection point PostGIS reports on a 422', async () => {
    const { fixture, http, element, button } = setup(['view', 'territory:manage']);
    http.expectOne(`${URL}?include_inactive=false`).flush([ZONE]);
    await fixture.whenStable();

    button('Editar')?.click();
    await fixture.whenStable();
    expect(FakeZoneMap.last?.mode()).toEqual({ kind: 'edit', zoneId: 'z1' });

    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    const request = http.expectOne(`${URL}/z1`);
    expect(request.request.method).toBe('PUT');
    request.flush(
      { detail: [{ loc: ['body', 'geometry'], msg: 'Self-intersection[-76.65 -11.95]' }] },
      { status: 422, statusText: 'Unprocessable Content' },
    );
    await fixture.whenStable();

    expect(element.querySelector('[role="alert"]')?.textContent).toContain('se cruza');
    expect(FakeZoneMap.last?.problem()).toEqual([-76.65, -11.95]);
  });

  it('asks for a polygon before saving', async () => {
    const { fixture, http, element, button } = setup(['view', 'territory:manage']);
    http.expectOne(`${URL}?include_inactive=false`).flush([]);
    await fixture.whenStable();
    button('Nueva zona')?.click();
    await fixture.whenStable();

    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    await fixture.whenStable();

    http.expectNone(URL);
    expect(element.querySelector('[role="alert"]')?.textContent).toContain('Falta dibujar');
  });
});
