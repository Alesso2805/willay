import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { ContactsPage } from './contacts-page';
import { Contact } from './contacts.api';

const URL = `${settings.apiUrl}/v1/contacts`;
const CARMEN: Contact = {
  id: 'c1',
  full_name: 'Carmen Jefatura COE',
  email: 'carmen@rimac.willay.test',
  telegram_linked: false,
  telegram_link_expires_at: null,
  groups: [{ id: 'g1', name: 'Jefatura COE' }],
  has_history: false,
};
const MANAGE = ['view', 'contacts:view_details', 'contacts:manage'];

function setup(permissions: string[]) {
  TestBed.configureTestingModule({
    imports: [ContactsPage],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      {
        provide: Session,
        useValue: { me: signal({ permissions, organization_timezone: 'America/Lima' }) },
      },
    ],
  });
  const fixture = TestBed.createComponent(ContactsPage);
  const http = TestBed.inject(HttpTestingController);
  const element = fixture.nativeElement as HTMLElement;
  const text = () => element.textContent ?? '';
  const button = (label: string) =>
    [...element.querySelectorAll('button')].find((b) => b.textContent?.trim() === label);
  const type = (name: string, value: string) => {
    const field = element.querySelector<HTMLInputElement>(`input[formcontrolname="${name}"]`)!;
    field.value = value;
    field.dispatchEvent(new Event('input'));
  };
  const listed = async (contacts: Contact[]) => {
    http.expectOne(URL).flush(contacts);
    await fixture.whenStable();
  };
  return { fixture, http, element, text, button, type, listed };
}

describe('ContactsPage', () => {
  beforeEach(() => vi.spyOn(window, 'confirm').mockReturnValue(true));
  afterEach(() => vi.restoreAllMocks());

  it('has no serious accessibility violations in the list, the form or the issued link', async () => {
    const { fixture, http, element, button, listed } = setup(MANAGE);
    await listed([CARMEN, { ...CARMEN, id: 'c2', email: null, groups: [] }]);
    expect(await seriousViolations(element)).toEqual([]);

    button('Nuevo contacto')?.click();
    await fixture.whenStable();
    expect(await seriousViolations(element)).toEqual([]);

    button('Cancelar')?.click();
    await fixture.whenStable();
    button('Generar enlace de Telegram')?.click();
    http
      .expectOne(`${URL}/c1/telegram-link`)
      .flush({ url: 'https://t.me/willay_bot?start=abc', expires_at: '2026-10-09T15:00:00Z' });
    http.expectOne(URL).flush([CARMEN]);
    await fixture.whenStable();
    expect(await seriousViolations(element)).toEqual([]);
  });

  it('says it is loading, not that there are no contacts, until the list arrives', async () => {
    const { fixture, text, listed } = setup(MANAGE);
    await fixture.whenStable();
    expect(text()).toContain('Cargando contactos…');
    expect(text()).not.toContain('Todavía no hay contactos.');
    await listed([]);
    expect(text()).toContain('Todavía no hay contactos.');
  });

  it('flags a contact no alert reaches, and one in no group', async () => {
    const { text, listed } = setup(MANAGE);
    await listed([
      CARMEN,
      { ...CARMEN, id: 'c2', full_name: 'Sin datos', email: null, groups: [] },
      { ...CARMEN, id: 'c3', full_name: 'Solo Telegram', email: null, telegram_linked: true },
    ]);
    expect(text()).toContain('3 contactos · 1 sin canal · 1 sin grupos');
    expect(text()).toContain('Sin correo');
    expect(text()).toContain('Sin canal');
    expect(text()).toContain('Sin grupos: no recibe alertas.');
    expect(text()).toContain('Grupos: Jefatura COE');
  });

  it('shows an operator the contacts but no action', async () => {
    const { text, button, listed } = setup(['view', 'contacts:view_details']);
    await listed([CARMEN]);
    expect(text()).toContain('carmen@rimac.willay.test');
    for (const label of ['Nuevo contacto', 'Editar', 'Generar enlace de Telegram', 'Eliminar']) {
      expect(button(label), label).toBeUndefined();
    }
  });

  it('explains to a role without access why it sees no contacts, without asking the API', async () => {
    const { fixture, http, text } = setup(['view']);
    await fixture.whenStable();
    http.expectNone(URL);
    expect(text()).toContain('Tu rol no permite ver los contactos');
    expect(text()).not.toContain('Cargando contactos…');
  });

  it('creates a contact without email, sending none rather than an empty one', async () => {
    const { fixture, http, text, button, type, listed } = setup(MANAGE);
    await listed([]);
    button('Nuevo contacto')?.click();
    await fixture.whenStable();
    type('full_name', '  Lucho Quispe ');
    button('Guardar')?.click();

    const request = http.expectOne({ method: 'POST', url: URL });
    expect(request.request.body).toEqual({ full_name: 'Lucho Quispe', email: null });
    request.flush({ ...CARMEN, id: 'c9', full_name: 'Lucho Quispe', email: null });
    http.expectOne(URL).flush([]);
    await fixture.whenStable();
    expect(text()).toContain('Contacto Lucho Quispe creado.');
    expect(button('Guardar')).toBeUndefined();
  });

  it('keeps the form open with the API explanation when it refuses the data', async () => {
    const { fixture, http, text, button, type, listed } = setup(MANAGE);
    await listed([CARMEN]);
    button('Editar')?.click();
    await fixture.whenStable();
    type('email', 'carmen@rimac');
    button('Guardar')?.click();
    http
      .expectOne(`${URL}/c1`)
      .flush(
        { detail: [{ loc: ['body', 'email'], msg: 'Correo no válido', type: 'value_error' }] },
        { status: 422, statusText: 'Unprocessable' },
      );
    await fixture.whenStable();
    expect(text()).toContain('Correo no válido');
    expect(button('Guardar')).toBeDefined();
  });

  it('shows a Telegram link once, with its expiry, until the admin dismisses it', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    const { fixture, http, element, text, button, listed } = setup(MANAGE);
    await listed([CARMEN]);
    button('Generar enlace de Telegram')?.click();
    http
      .expectOne({ method: 'POST', url: `${URL}/c1/telegram-link` })
      .flush({ url: 'https://t.me/willay_bot?start=abc', expires_at: '2026-10-09T15:00:00Z' });
    http.expectOne(URL).flush([{ ...CARMEN, telegram_link_expires_at: '2026-10-09T15:00:00Z' }]);
    await fixture.whenStable();

    const field = element.querySelector<HTMLInputElement>('input[aria-label="Enlace de Telegram"]');
    expect(field?.value).toBe('https://t.me/willay_bot?start=abc');
    expect(text()).toContain('no se volverá a mostrar');
    expect(text()).toContain('hasta el 09/10/2026 10:00'); // Lima time
    expect(text()).toContain('Enlace de Telegram pendiente');

    button('Copiar')?.click();
    await fixture.whenStable();
    expect(writeText).toHaveBeenCalledWith('https://t.me/willay_bot?start=abc');
    expect(button('Copiado')).toBeDefined();

    button('Ya lo compartí')?.click();
    await fixture.whenStable();
    expect(element.querySelector('input[aria-label="Enlace de Telegram"]')).toBeNull();
    expect(button('Generar otro enlace')).toBeDefined();
  });

  it('explains that the bot is not configured', async () => {
    const { fixture, http, text, button, listed } = setup(MANAGE);
    await listed([CARMEN]);
    button('Generar enlace de Telegram')?.click();
    http
      .expectOne(`${URL}/c1/telegram-link`)
      .flush(
        { detail: 'El bot de Telegram no está configurado (WILLAY_TELEGRAM_BOT_USERNAME).' },
        { status: 503, statusText: 'Unavailable' },
      );
    await fixture.whenStable();
    expect(text()).toContain('El bot de Telegram no está configurado');
  });

  it('unlinks Telegram only after confirming', async () => {
    const { fixture, http, button, listed } = setup(MANAGE);
    await listed([{ ...CARMEN, telegram_linked: true }]);
    vi.mocked(window.confirm).mockReturnValueOnce(false);
    button('Desvincular Telegram')?.click();
    http.expectNone(`${URL}/c1/telegram`);

    button('Desvincular Telegram')?.click();
    http
      .expectOne({ method: 'DELETE', url: `${URL}/c1/telegram` })
      .flush({ ...CARMEN, telegram_linked: false });
    http.expectOne(URL).flush([CARMEN]);
    await fixture.whenStable();
    expect(button('Generar enlace de Telegram')).toBeDefined();
  });

  it('offers removing a contact with history from its groups instead of deleting it', async () => {
    const { fixture, http, text, button, listed } = setup(MANAGE);
    await listed([{ ...CARMEN, has_history: true }]);
    expect(button('Eliminar')).toBeUndefined();
    button('Quitar de sus grupos')?.click();
    http
      .expectOne({ method: 'POST', url: `${URL}/c1/remove-from-groups` })
      .flush({ ...CARMEN, has_history: true, groups: [] });
    http.expectOne(URL).flush([{ ...CARMEN, has_history: true, groups: [] }]);
    await fixture.whenStable();
    expect(text()).toContain('Carmen Jefatura COE ya no está en ningún grupo.');
    expect(text()).toContain('Con historial: se conserva');
    expect(button('Quitar de sus grupos')).toBeUndefined();
  });

  it('explains a 409 when the contact gained history meanwhile, and reloads it', async () => {
    const { fixture, http, text, button, listed } = setup(MANAGE);
    await listed([CARMEN]);
    button('Eliminar')?.click();
    const detail =
      'Carmen Jefatura COE tiene historial (alertas o confirmaciones) y no se puede borrar.';
    http
      .expectOne({ method: 'DELETE', url: `${URL}/c1` })
      .flush({ detail }, { status: 409, statusText: 'Conflict' });
    http.expectOne(URL).flush([{ ...CARMEN, has_history: true }]);
    await fixture.whenStable();
    expect(text()).toContain(detail);
    expect(button('Quitar de sus grupos')).toBeDefined();
  });
});
