import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { settings } from '../settings';
import { browserLanguage, currentLanguage, t } from './i18n';
import { LanguageService, acceptLanguageInterceptor } from './language';

function setup() {
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(withInterceptors([acceptLanguageInterceptor])),
      provideHttpClientTesting(),
    ],
  });
  return {
    service: TestBed.inject(LanguageService),
    http: TestBed.inject(HttpTestingController),
  };
}

describe('browserLanguage', () => {
  it('takes the first language Willay speaks, whatever the region', () => {
    expect(browserLanguage(['en-GB', 'es'])).toBe('en');
    expect(browserLanguage(['fr-FR', 'es-PE'])).toBe('es');
    expect(browserLanguage(['fr', 'de'])).toBeNull();
  });
});

describe('LanguageService', () => {
  afterEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it('starts in this browser’s last language, before the browser’s own', async () => {
    localStorage.setItem('willay.language', 'en');
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['es-PE']);
    const { service } = setup();
    await service.start();
    expect(service.current()).toBe('en');
    expect(t('nav.home')).toBe('Home');
    expect(document.documentElement.lang).toBe('en');
  });

  it('starts in the browser’s language, and in Spanish when Willay does not speak it', async () => {
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['en-US']);
    const first = setup();
    await first.service.start();
    expect(first.service.current()).toBe('en');

    TestBed.resetTestingModule();
    localStorage.clear();
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['fr-FR']);
    const second = setup();
    await second.service.start();
    expect(second.service.current()).toBe('es');
  });

  it('the language saved for the user wins once signed in', async () => {
    const { service, http } = setup();
    await service.adopt('en');
    expect(service.current()).toBe('en');
    await service.adopt(null); // never chose one: stays as it is
    expect(service.current()).toBe('en');
    http.expectNone(`${settings.apiUrl}/v1/me/language`);
  });

  it('saves the language the user picks', async () => {
    const { service, http } = setup();
    await service.choose('en', true);
    expect(currentLanguage()).toBe('en');
    const request = http.expectOne(`${settings.apiUrl}/v1/me/language`);
    expect(request.request.method).toBe('PUT');
    expect(request.request.body).toEqual({ language: 'en' });
    request.flush(null, { status: 204, statusText: 'No Content' });
  });

  it('a language picked before signing in is saved once signed in, over the old one', async () => {
    const { service, http } = setup();
    await service.choose('en', false);
    http.expectNone(`${settings.apiUrl}/v1/me/language`);

    await service.adopt('es'); // what the user had saved before
    expect(service.current()).toBe('en');
    http.expectOne(`${settings.apiUrl}/v1/me/language`).flush(null);
  });

  it('pressing the language already on screen before signing in still counts as a choice', async () => {
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['en-US']);
    const { service, http } = setup();
    await service.start(); // English, only because the browser is
    await service.choose('en', false);

    await service.adopt('es');
    expect(service.current()).toBe('en');
    expect(http.expectOne(`${settings.apiUrl}/v1/me/language`).request.body).toEqual({
      language: 'en',
    });
  });

  it('asks the API for messages in the language on screen', async () => {
    const { service, http } = setup();
    await service.choose('en', false);
    TestBed.inject(HttpClient).get(`${settings.apiUrl}/v1/zones`).subscribe();
    TestBed.inject(HttpClient).get('http://localhost:8080/realms/willay').subscribe();
    expect(
      http.expectOne(`${settings.apiUrl}/v1/zones`).request.headers.get('Accept-Language'),
    ).toBe('en');
    const keycloak = http.expectOne('http://localhost:8080/realms/willay');
    expect(keycloak.request.headers.has('Accept-Language')).toBe(false); // only our API
  });
});
