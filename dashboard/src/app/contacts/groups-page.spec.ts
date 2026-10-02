import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { Zone } from '../zones/zones.api';
import { Contact } from './contacts.api';
import { ContactGroup } from './groups.api';
import { GroupsPage } from './groups-page';

const URL = `${settings.apiUrl}/v1/contact-groups`;
const CONTACTS_URL = `${settings.apiUrl}/v1/contacts`;
const ZONES_URL = `${settings.apiUrl}/v1/zones?include_inactive=false`;
const ROSA = { id: 'c1', name: 'Rosa Brigada' };
const LUCHO = { id: 'c2', name: 'Lucho Quispe' };
const BRIGADE: ContactGroup = {
  id: 'g1',
  name: 'Brigada Chosica',
  zone: { id: 'z1', name: 'Chosica' },
  members: [LUCHO, ROSA],
  policies: [{ id: 'p1', name: 'Protocolo Rímac' }],
};
const SPARE: ContactGroup = { id: 'g2', name: 'Reserva', zone: null, members: [], policies: [] };
const contact = (ref: { id: string; name: string }, email: string | null): Contact => ({
  id: ref.id,
  full_name: ref.name,
  email,
  telegram_linked: false,
  telegram_link_expires_at: null,
  groups: [],
  has_history: false,
});
const ZONE = { id: 'z1', name: 'Chosica' } as Zone;
const MANAGE = ['view', 'contacts:view_details', 'contacts:manage'];

function setup(permissions: string[]) {
  TestBed.configureTestingModule({
    imports: [GroupsPage],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      { provide: Session, useValue: { me: signal({ permissions }) } },
    ],
  });
  const fixture = TestBed.createComponent(GroupsPage);
  const http = TestBed.inject(HttpTestingController);
  const element = fixture.nativeElement as HTMLElement;
  const text = () => element.textContent ?? '';
  const button = (label: string) =>
    [...element.querySelectorAll('button')].find((b) => b.textContent?.trim() === label);
  const card = (name: string) =>
    [...element.querySelectorAll('li')].find((li) => li.textContent?.includes(name))!;
  const listed = async (groups: ContactGroup[]) => {
    http.expectOne(URL).flush(groups);
    if (permissions.includes('contacts:manage')) {
      http.expectOne(CONTACTS_URL).flush([contact(ROSA, 'rosa@x.pe'), contact(LUCHO, null)]);
      http.expectOne(ZONES_URL).flush([ZONE]);
    }
    await fixture.whenStable();
  };
  return { fixture, http, element, text, button, card, listed };
}

describe('GroupsPage', () => {
  beforeEach(() => vi.spyOn(window, 'confirm').mockReturnValue(true));
  afterEach(() => vi.restoreAllMocks());

  it('has no serious accessibility violations in the list or the form', async () => {
    const { fixture, element, button, listed } = setup(MANAGE);
    await listed([BRIGADE, SPARE]);
    expect(await seriousViolations(element)).toEqual([]);
    button('Nuevo grupo')?.click();
    await fixture.whenStable();
    expect(await seriousViolations(element)).toEqual([]);
  });

  it('shows each group with its zone, members and the policy that notifies it', async () => {
    const { text, card, listed } = setup(MANAGE);
    await listed([BRIGADE, SPARE]);
    expect(text()).toContain('2 grupos · 1 sin miembros · 1 sin política');
    expect(card('Brigada Chosica').textContent).toContain('Zona Chosica');
    expect(card('Brigada Chosica').textContent).toContain('Lucho Quispe, Rosa Brigada');
    expect(card('Brigada Chosica').textContent).toContain('Protocolo Rímac');
    expect(card('Reserva').textContent).toContain('Sin miembros');
    expect(card('Reserva').textContent).toContain('Ninguna política lo usa');
  });

  it('shows an operator the groups but no action, without loading the form data', async () => {
    const { http, button, text, listed } = setup(['view', 'contacts:view_details']);
    await listed([BRIGADE]);
    http.expectNone(CONTACTS_URL);
    expect(text()).toContain('Brigada Chosica');
    expect(button('Nuevo grupo')).toBeUndefined();
    expect(button('Editar')).toBeUndefined();
  });

  it('explains to a role without access why it sees no groups', async () => {
    const { fixture, http, text } = setup(['view']);
    await fixture.whenStable();
    http.expectNone(URL);
    expect(text()).toContain('Tu rol no permite ver los grupos');
  });

  it('only offers deleting a group no policy notifies', async () => {
    const { card, listed } = setup(MANAGE);
    await listed([BRIGADE, SPARE]);
    const buttons = (name: string) =>
      [...card(name).querySelectorAll('button')].map((b) => b.textContent?.trim());
    expect(buttons('Brigada Chosica')).toEqual(['Editar']);
    expect(card('Brigada Chosica').textContent).toContain('Lo usa una política');
    expect(buttons('Reserva')).toEqual(['Editar', 'Eliminar']);
  });

  it('edits the members and zone, sending the whole member list', async () => {
    const { fixture, http, element, text, button, listed } = setup(MANAGE);
    await listed([BRIGADE]);
    button('Editar')?.click();
    await fixture.whenStable();
    expect(text()).toContain('(sin canal: no le llegan alertas)'); // Lucho has no channel
    const boxes = [...element.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
    expect(boxes.map((b) => b.checked)).toEqual([true, true]);
    boxes[1].click(); // Lucho out
    const zone = element.querySelector<HTMLSelectElement>('select[formcontrolname="zone_id"]')!;
    zone.value = '';
    zone.dispatchEvent(new Event('change'));
    button('Guardar')?.click();

    const request = http.expectOne({ method: 'PUT', url: `${URL}/g1` });
    expect(request.request.body).toEqual({
      name: 'Brigada Chosica',
      zone_id: null,
      member_ids: ['c1'],
    });
    request.flush({ ...BRIGADE, zone: null, members: [ROSA] });
    http.expectOne(URL).flush([{ ...BRIGADE, zone: null, members: [ROSA] }]);
    await fixture.whenStable();
    expect(text()).toContain('Grupo Brigada Chosica guardado.');
  });

  it('keeps the form open with the API explanation for a duplicate name', async () => {
    const { fixture, http, element, text, button, listed } = setup(MANAGE);
    await listed([BRIGADE]);
    button('Nuevo grupo')?.click();
    await fixture.whenStable();
    const name = element.querySelector<HTMLInputElement>('input[formcontrolname="name"]')!;
    name.value = 'Brigada Chosica';
    name.dispatchEvent(new Event('input'));
    button('Guardar')?.click();
    http
      .expectOne({ method: 'POST', url: URL })
      .flush(
        { detail: 'Ya hay un grupo con ese nombre.' },
        { status: 409, statusText: 'Conflict' },
      );
    await fixture.whenStable();
    expect(text()).toContain('Ya hay un grupo con ese nombre.');
    expect(button('Guardar')).toBeDefined();
  });

  it('explains a 409 when a policy started using the group meanwhile, and reloads', async () => {
    const { fixture, http, text, button, listed } = setup(MANAGE);
    await listed([SPARE]);
    button('Eliminar')?.click();
    const detail =
      'Reserva se usa en «Protocolo Rímac». Quítalo de esa política antes de borrarlo.';
    http
      .expectOne({ method: 'DELETE', url: `${URL}/g2` })
      .flush({ detail }, { status: 409, statusText: 'Conflict' });
    http.expectOne(URL).flush([{ ...SPARE, policies: BRIGADE.policies }]);
    await fixture.whenStable();
    expect(text()).toContain(detail);
    expect(button('Eliminar')).toBeUndefined();
  });
});
