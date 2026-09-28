import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { of } from 'rxjs';
import { App } from './app';
import { Me } from './session';
import { settings } from './settings';

const ME: Me = {
  user_id: 'c144b510-2abd-4844-ad5e-13e700b29fba',
  email: 'operador@rimac.vigia.test',
  full_name: 'Óscar Operador Rímac',
  organization_id: '01a0dc43-cd2d-7522-8430-867cee8f89ce',
  keycloak_org_id: '1d44f4b3-b1df-457f-b717-20926a20166e',
  roles: ['operator'],
};

function setup(isAuthenticated: boolean) {
  const oidc = {
    checkAuth: () => of({ isAuthenticated }),
    authorize: vi.fn(),
    logoff: vi.fn(() => of(null)),
  };
  TestBed.configureTestingModule({
    imports: [App],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: OidcSecurityService, useValue: oidc },
    ],
  });
  const fixture = TestBed.createComponent(App);
  const http = TestBed.inject(HttpTestingController);
  const text = () => (fixture.nativeElement as HTMLElement).textContent ?? '';
  return { fixture, http, oidc, text };
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

  it('shows the user organization and roles after login', async () => {
    const { fixture, http, text } = setup(true);
    http.expectOne(`${settings.apiUrl}/v1/me`).flush(ME);
    await fixture.whenStable();
    expect(text()).toContain(ME.organization_id);
    expect(text()).toContain('Operación');
    expect(text()).toContain('Cerrar sesión');
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
