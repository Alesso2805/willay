import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { Organization } from './organization.api';
import { OrganizationPage, timezoneOptions } from './organization-page';

const URL = `${settings.apiUrl}/v1/organization`;
const RIMAC: Organization = {
  id: 'o1',
  name: 'Demo Rímac',
  language: 'es',
  timezone: 'America/Lima',
};

function setup(permissions: string[]) {
  const useOrganizationTimezone = vi.fn();
  TestBed.configureTestingModule({
    imports: [OrganizationPage],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: Session, useValue: { me: signal({ permissions }), useOrganizationTimezone } },
    ],
  });
  const fixture = TestBed.createComponent(OrganizationPage);
  const http = TestBed.inject(HttpTestingController);
  const element = fixture.nativeElement as HTMLElement;
  const text = () => element.textContent?.replace(/\s+/g, ' ') ?? '';
  const select = (id: string) => element.querySelector<HTMLSelectElement>(`#${id}`)!;
  const loaded = async (organization: Organization = RIMAC) => {
    http.expectOne(URL).flush(organization);
    await fixture.whenStable();
  };
  return { fixture, http, element, text, select, loaded, useOrganizationTimezone };
}

describe('OrganizationPage', () => {
  it('lets an admin change the language and the time zone, and the session follows', async () => {
    const { fixture, http, element, text, select, loaded, useOrganizationTimezone } = setup([
      'view',
      'organization:manage',
    ]);
    await loaded();
    expect(text()).toContain('Cómo escribe Willay para Demo Rímac');
    expect([select('organization-language').value, select('organization-timezone').value]).toEqual([
      'es',
      'America/Lima',
    ]);

    select('organization-language').value = 'en';
    select('organization-language').dispatchEvent(new Event('change'));
    select('organization-timezone').value = 'America/Bogota';
    select('organization-timezone').dispatchEvent(new Event('change'));
    element.querySelector<HTMLButtonElement>('button[type="submit"]')!.click();

    const request = http.expectOne({ method: 'PUT', url: URL });
    expect(request.request.body).toEqual({ language: 'en', timezone: 'America/Bogota' });
    request.flush({ ...RIMAC, language: 'en', timezone: 'America/Bogota' });
    await fixture.whenStable();
    expect(text()).toContain('Guardado: se aplica desde el próximo aviso.');
    expect(useOrganizationTimezone).toHaveBeenCalledWith('America/Bogota');
  });

  it('says what time it is in the zone picked', async () => {
    const { fixture, select, element, loaded } = setup(['view', 'organization:manage']);
    await loaded();
    select('organization-timezone').value = 'Asia/Tokyo';
    select('organization-timezone').dispatchEvent(new Event('change'));
    await fixture.whenStable();
    const help = element.querySelector('#organization-timezone-help')?.textContent ?? '';
    const tokyo = new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Asia/Tokyo',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    }).format(new Date());
    expect(help).toContain(tokyo.slice(0, 2)); // the hour in Tokyo, not in Lima
  });

  it('explains the API refusing the time zone', async () => {
    const { fixture, http, element, text, loaded } = setup(['view', 'organization:manage']);
    await loaded();
    element.querySelector<HTMLButtonElement>('button[type="submit"]')!.click();
    http.expectOne({ method: 'PUT', url: URL }).flush(
      {
        code: 'organization_timezone_unknown',
        detail: [{ loc: ['body', 'timezone'], msg: 'No es una zona horaria conocida' }],
      },
      { status: 422, statusText: 'Unprocessable' },
    );
    await fixture.whenStable();
    expect(text()).toContain('No es una zona horaria conocida');
  });

  it('shows the settings read-only to anyone else', async () => {
    const { element, text, select, loaded } = setup(['view']);
    await loaded();
    expect(text()).toContain('Solo un administrador cambia esta configuración.');
    expect(select('organization-language').disabled).toBe(true);
    expect(select('organization-timezone').disabled).toBe(true);
    expect(element.querySelector('button[type="submit"]')).toBeNull();
  });

  it('has no serious accessibility violations', async () => {
    const { element, loaded } = setup(['view', 'organization:manage']);
    await loaded();
    expect(await seriousViolations(element)).toEqual([]);
  });
});

describe('timezoneOptions', () => {
  it('keeps the saved zone even if the browser does not know it', () => {
    expect(timezoneOptions('America/Lima', ['America/Lima', 'UTC'])).toEqual([
      'America/Lima',
      'UTC',
    ]);
    expect(timezoneOptions('Etc/Old', ['UTC'])).toEqual(['Etc/Old', 'UTC']);
  });
});
