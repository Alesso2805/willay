import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { ContactGroup } from './groups.api';
import { Policy } from './policies.api';
import { PoliciesPage } from './policies-page';
import { formErrors, inputOf, minutesOf } from './policy-form';

const URL = `${settings.apiUrl}/v1/escalation-policies`;
const GROUPS_URL = `${settings.apiUrl}/v1/contact-groups`;
const GROUPS: ContactGroup[] = [
  { id: 'g1', name: 'Operadores de turno', zone: null, members: [], policies: [] },
  { id: 'g2', name: 'Brigada Chosica', zone: null, members: [], policies: [] },
];
const RIMAC: Policy = {
  id: 'p1',
  name: 'Protocolo Rímac',
  created_at: '2026-10-01T00:00:00Z',
  levels: [
    {
      level_order: 1,
      wait_s: 120,
      targets: [
        { contact_group_id: 'g1', contact_group_name: 'Operadores de turno', channel: 'email' },
      ],
    },
    {
      level_order: 2,
      wait_s: 180,
      targets: [
        { contact_group_id: 'g2', contact_group_name: 'Brigada Chosica', channel: 'email' },
        { contact_group_id: 'g2', contact_group_name: 'Brigada Chosica', channel: 'telegram' },
      ],
    },
  ],
};
const MANAGE = ['view', 'contacts:view_details', 'policies:manage'];

function setup(permissions: string[]) {
  TestBed.configureTestingModule({
    imports: [PoliciesPage],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      { provide: Session, useValue: { me: signal({ permissions }) } },
    ],
  });
  const fixture = TestBed.createComponent(PoliciesPage);
  const http = TestBed.inject(HttpTestingController);
  const element = fixture.nativeElement as HTMLElement;
  const text = () => element.textContent?.replace(/\s+/g, ' ') ?? '';
  const button = (label: string) =>
    [...element.querySelectorAll('button')].find((b) => b.textContent?.trim() === label);
  const listed = async (policies: Policy[] = [RIMAC]) => {
    http.expectOne(URL).flush(policies);
    http.expectOne(GROUPS_URL).flush(GROUPS);
    await fixture.whenStable();
  };
  const type = (selector: string, value: string) => {
    const input = element.querySelector<HTMLInputElement>(selector)!;
    input.value = value;
    input.dispatchEvent(new Event('input'));
  };
  const check = (label: string) => {
    const box = element.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
    box.click();
  };
  return { fixture, http, element, text, button, listed, type, check };
}

describe('PoliciesPage', () => {
  beforeEach(() => vi.spyOn(window, 'confirm').mockReturnValue(true));
  afterEach(() => vi.restoreAllMocks());

  it('says each policy in words: who each level alerts and how long it waits', async () => {
    const { text, listed } = setup(MANAGE);
    await listed();
    expect(text()).toContain('Nivel 1: avisa a Operadores de turno (Correo)');
    expect(text()).toContain('Si nadie confirma en 2 min, se avisa al nivel 2.');
    expect(text()).toContain('avisa a Brigada Chosica (Correo), Brigada Chosica (Telegram)');
    expect(text()).toContain('Si nadie confirma en 3 min, el escalamiento se agota.');
  });

  it('creates a policy level by level, in minutes, with groups per channel', async () => {
    const { fixture, http, text, button, listed, type, check } = setup(MANAGE);
    await listed([]);
    button('Nueva política')?.click();
    await fixture.whenStable();
    expect(text()).toContain('también se aplican a los incidentes en curso');

    type('#policy-name', '  Protocolo nuevo ');
    type('#policy-wait-0', '1.5');
    check('Nivel 1: Operadores de turno por Correo');
    button('Agregar nivel')?.click();
    await fixture.whenStable();
    type('#policy-wait-1', '5');
    check('Nivel 2: Brigada Chosica por Telegram');
    button('Guardar')?.click();

    const request = http.expectOne({ method: 'POST', url: URL });
    expect(request.request.body).toEqual({
      name: 'Protocolo nuevo',
      levels: [
        { wait_s: 90, targets: [{ contact_group_id: 'g1', channel: 'email' }] },
        { wait_s: 300, targets: [{ contact_group_id: 'g2', channel: 'telegram' }] },
      ],
    });
    request.flush({ ...RIMAC, id: 'p2', name: 'Protocolo nuevo' });
    await listed([RIMAC]);
    expect(text()).toContain('Política Protocolo nuevo creada.');
  });

  it('shows each problem next to its field', async () => {
    const { fixture, http, element, text, button, listed } = setup(MANAGE);
    await listed();
    button('Editar')?.click();
    await fixture.whenStable();
    button('Guardar')?.click();
    http.expectOne({ method: 'PUT', url: `${URL}/p1` }).flush(
      {
        code: 'policy_level_wait',
        detail: [
          {
            loc: ['body', 'levels', 1, 'wait_s'],
            msg: 'Nivel 2: la espera va de 1 a 86400 segundos.',
            code: 'policy_level_wait',
          },
        ],
      },
      { status: 422, statusText: 'Unprocessable' },
    );
    await fixture.whenStable();
    // In minutes, as the screen asks, not in the API's seconds.
    expect(element.querySelector('#policy-wait-error-1')?.textContent).toContain(
      'Nivel 2: la espera va de 1 segundo a 24 horas. Escríbela en minutos',
    );
    expect(element.querySelector('#policy-wait-1')?.getAttribute('aria-invalid')).toBe('true');
    expect(element.querySelector('#policy-wait-0')?.getAttribute('aria-invalid')).toBeNull();
    expect(text()).toContain('Editar Protocolo Rímac'); // the form stays open

    const wait = element.querySelector<HTMLInputElement>('#policy-wait-1')!;
    wait.value = '3';
    wait.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    expect(element.querySelector('#policy-wait-error-1')).toBeNull(); // gone once corrected
  });

  it('puts a taken name under the name', async () => {
    const { fixture, http, element, button, listed } = setup(MANAGE);
    await listed();
    button('Editar')?.click();
    await fixture.whenStable();
    button('Guardar')?.click();
    http
      .expectOne({ method: 'PUT', url: `${URL}/p1` })
      .flush(
        { detail: 'Ya hay una política con ese nombre.', code: 'policy_name_taken' },
        { status: 409, statusText: 'Conflict' },
      );
    await fixture.whenStable();
    expect(element.querySelector('#policy-name-error')?.textContent).toContain(
      'Ya hay una política',
    );
  });

  it('reorders levels: their order is their position', async () => {
    const { fixture, http, button, listed } = setup(MANAGE);
    await listed();
    button('Editar')?.click();
    await fixture.whenStable();
    button('Bajar')?.click();
    await fixture.whenStable();
    button('Guardar')?.click();
    const body = http.expectOne({ method: 'PUT', url: `${URL}/p1` }).request.body;
    expect(body.levels.map((l: { wait_s: number }) => l.wait_s)).toEqual([180, 120]);
  });

  it('explains why a policy in use cannot be deleted', async () => {
    const { http, text, button, listed } = setup(MANAGE);
    await listed();
    button('Eliminar')?.click();
    const detail = 'Alguna regla usa esta política: cámbiala en esas reglas antes de borrarla.';
    http
      .expectOne({ method: 'DELETE', url: `${URL}/p1` })
      .flush({ detail, code: 'policy_in_use' }, { status: 409, statusText: 'Conflict' });
    await listed();
    expect(text()).toContain(detail);
  });

  it('shows an operator the policies but no action', async () => {
    const { text, button, listed } = setup(['view', 'contacts:view_details']);
    await listed();
    expect(text()).toContain('Protocolo Rímac');
    for (const label of ['Nueva política', 'Editar', 'Eliminar']) {
      expect(button(label), label).toBeUndefined();
    }
  });

  it('has no serious accessibility violations in the list and the form', async () => {
    const { fixture, element, button, listed } = setup(MANAGE);
    await listed();
    expect(await seriousViolations(element)).toEqual([]);
    button('Editar')?.click();
    await fixture.whenStable();
    expect(await seriousViolations(element)).toEqual([]);
  });
});

describe('policy form', () => {
  it('writes waits in minutes and reads them back, commas included', () => {
    expect([minutesOf(120), minutesOf(90), minutesOf(3600)]).toEqual(['2', '1.5', '60']);
    const input = inputOf(' P ', [{ minutes: '2,5', targets: new Set(['g1:email']) }]);
    expect(input).toEqual({
      name: 'P',
      levels: [{ wait_s: 150, targets: [{ contact_group_id: 'g1', channel: 'email' }] }],
    });
    expect(inputOf('P', [{ minutes: 'x', targets: new Set() }]).levels[0].wait_s).toBe(0);
  });

  it('sends each problem of a 422 to its field', () => {
    const error = new HttpErrorResponse({
      status: 422,
      error: {
        detail: [
          { loc: ['body', 'name'], msg: 'nombre' },
          { loc: ['body', 'levels', 0, 'targets'], msg: 'grupos' },
          { loc: ['body', 'levels'], msg: 'niveles' },
        ],
      },
    });
    expect(formErrors(error)).toEqual({
      name: 'nombre',
      levels: 'niveles',
      perLevel: { 0: { targets: 'grupos' } },
    });
    expect(formErrors(new HttpErrorResponse({ status: 500 }))).toBeNull();
  });
});
