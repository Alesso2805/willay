import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { of } from 'rxjs';
import { App } from './app';
import { routes } from './app.routes';
import { FakeLiveEvents, provideFakeLiveEvents } from './realtime/live-events.testing';
import { Me } from './session';
import { settings } from './settings';
import { seriousViolations } from './ui/axe';

const ME: Me = {
  user_id: 'c144b510-2abd-4844-ad5e-13e700b29fba',
  email: 'operador@rimac.willay.test',
  full_name: 'Óscar Operador Rímac',
  organization_id: '01a0dc43-cd2d-7522-8430-867cee8f89ce',
  keycloak_org_id: '1d44f4b3-b1df-457f-b717-20926a20166e',
  organization_name: 'Demo Rímac',
  organization_timezone: 'America/Lima',
  roles: ['operator'],
  permissions: ['view', 'incidents:acknowledge', 'incidents:resolve', 'territory:manage'],
};

function navLabels(root: HTMLElement): string[] {
  return [...root.querySelectorAll('nav[aria-label="Principal"] a')].map((a) => a.textContent?.trim() ?? '');
}

function setup(isAuthenticated: boolean) {
  const oidc = {
    checkAuth: () => of({ isAuthenticated }),
    authorize: vi.fn(),
    logoff: vi.fn(() => of(null)),
  };
  const live = new FakeLiveEvents();
  TestBed.configureTestingModule({
    imports: [App],
    providers: [
      provideRouter(routes),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: OidcSecurityService, useValue: oidc },
      provideFakeLiveEvents(live),
    ],
  });
  const fixture = TestBed.createComponent(App);
  const http = TestBed.inject(HttpTestingController);
  const text = () => (fixture.nativeElement as HTMLElement).textContent ?? '';
  return { fixture, http, oidc, text, live };
}

describe('App', () => {
  it('states that it does not replace official warning systems', async () => {
    const { fixture, text } = setup(false);
    await fixture.whenStable();
    expect(text()).toContain('No reemplaza a los sistemas oficiales de alerta');
  });

  it('offers login when there is no session', async () => {
    const { fixture, oidc } = setup(false);
    await fixture.whenStable();
    const button = [...(fixture.nativeElement as HTMLElement).querySelectorAll('button')].find(
      (b) => b.textContent?.includes('Iniciar sesión'),
    );
    button?.click();
    expect(oidc.authorize).toHaveBeenCalled();
  });

  it('shows the user organization by name and roles after login', async () => {
    const { fixture, http, text } = setup(true);
    http.expectOne(`${settings.apiUrl}/v1/me`).flush(ME);
    await TestBed.inject(Router).navigateByUrl('/');
    await fixture.whenStable();
    expect(text()).toContain('Demo Rímac');
    expect(text()).not.toContain(ME.organization_id); // never the uuid
    expect(text()).toContain('America/Lima');
    expect(text()).toContain('Operación');
    expect(text()).toContain('Cerrar sesión');
    expect(navLabels(fixture.nativeElement)).toEqual(['Inicio', 'Mapa en vivo', 'Zonas', 'Estaciones']);
  });

  it('a user without roles only sees Inicio and why', async () => {
    const { fixture, http, text } = setup(true);
    http.expectOne(`${settings.apiUrl}/v1/me`).flush({ ...ME, roles: [], permissions: [] });
    await TestBed.inject(Router).navigateByUrl('/');
    await fixture.whenStable();
    expect(navLabels(fixture.nativeElement)).toEqual(['Inicio']);
    expect(text()).toContain('todavía no tiene un rol en Willay');
  });

  it('opens the live channel after login and says whether the data is live', async () => {
    const { fixture, http, text, live } = setup(true);
    http.expectOne(`${settings.apiUrl}/v1/me`).flush(ME);
    await fixture.whenStable();
    expect(live.status()).toBe('connecting');
    expect(text()).toContain('Conectando…');

    live.status.set('live');
    await fixture.whenStable();
    expect(text()).toContain('En vivo');
    expect(text()).not.toContain('Sin conexión en vivo');

    live.status.set('reconnecting');
    await fixture.whenStable();
    const alert = (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('Sin conexión en vivo');
    expect(alert?.textContent).toContain('cada 15 s');
  });

  it('opens no live channel for a user who may not see the data', async () => {
    const { fixture, http, text, live } = setup(true);
    http.expectOne(`${settings.apiUrl}/v1/me`).flush({ ...ME, roles: [], permissions: [] });
    await fixture.whenStable();
    expect(live.status()).toBe('off');
    expect(text()).not.toContain('En vivo');
  });

  it('folds the navigation behind a menu button on narrow screens', async () => {
    const { fixture, http } = setup(true);
    http.expectOne(`${settings.apiUrl}/v1/me`).flush(ME);
    await fixture.whenStable();
    const root = fixture.nativeElement as HTMLElement;
    const button = root.querySelector<HTMLButtonElement>('button[aria-controls="menu-principal"]');
    const menu = root.querySelector('#menu-principal');
    expect(button?.getAttribute('aria-expanded')).toBe('false');
    expect(menu?.classList).toContain('hidden'); // lg:flex shows it from 1024 px

    button?.click();
    await fixture.whenStable();
    expect(button?.getAttribute('aria-expanded')).toBe('true');
    expect(menu?.classList).not.toContain('hidden');
  });

  it('has no serious accessibility violations, with or without a session', async () => {
    const anonymous = setup(false);
    await anonymous.fixture.whenStable();
    expect(await seriousViolations(anonymous.fixture.nativeElement)).toEqual([]);
    TestBed.resetTestingModule();

    const { fixture, http } = setup(true);
    http.expectOne(`${settings.apiUrl}/v1/me`).flush(ME);
    await TestBed.inject(Router).navigateByUrl('/');
    await fixture.whenStable();
    expect(await seriousViolations(fixture.nativeElement)).toEqual([]);
  });

  it('explains a 403 from the API (zero or several organizations)', async () => {
    const { fixture, http, text } = setup(true);
    http
      .expectOne(`${settings.apiUrl}/v1/me`)
      .flush({ detail: 'x' }, { status: 403, statusText: 'Forbidden' });
    await fixture.whenStable();
    expect(text()).toContain('exactamente una organización');
  });
});
