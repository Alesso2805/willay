import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Session } from '../session';
import { settings } from '../settings';
import { Station } from '../stations/stations.api';
import { seriousViolations } from '../ui/axe';
import { Zone } from '../zones/zones.api';
import { RulesPage } from './rules-page';
import { Rule, RulePreview } from './rules.api';

const API = settings.apiUrl;
const CHOSICA = { id: 'z1', name: 'Chosica' } as Zone;
const station = (id: string, code: string, unit: string, zoneId = 'z1'): Station =>
  ({
    id,
    code,
    name: `Estación ${code}`,
    unit,
    status: 'active',
    expected_interval_s: 10,
    silence_multiplier: 3,
    zones: [{ zone_id: zoneId, position: 'in_zone' }],
  }) as Station;
const BRIDGE = station('s1', 'RIM-CHO-01', 'm');
const ELSEWHERE = station('s9', 'RIM-HUA-01', 'm3/s', 'z2');
const THRESHOLD: Rule = {
  id: 'r1',
  type: 'threshold',
  zone: { id: 'z1', name: 'Chosica' },
  station: { id: 's1', code: 'RIM-CHO-01', name: 'Puente', unit: 'm' },
  params: { operator: 'gt', value: 3.5, consecutive: 2 },
  severity: 'warning',
  escalation_policy: { id: 'p1', name: 'Protocolo Rímac' },
  cooldown_s: 1800,
  is_active: true,
  created_at: '',
  updated_at: '',
};
const SILENCE: Rule = {
  ...THRESHOLD,
  id: 'r2',
  type: 'silence',
  params: {},
  station: null,
  severity: 'critical',
};
const MANAGE = ['view', 'rules:manage'];

function setup(permissions: string[]) {
  TestBed.configureTestingModule({
    imports: [RulesPage],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      {
        provide: Session,
        useValue: { me: signal({ permissions, organization_timezone: 'America/Lima' }) },
      },
    ],
  });
  const fixture = TestBed.createComponent(RulesPage);
  const http = TestBed.inject(HttpTestingController);
  const element = fixture.nativeElement as HTMLElement;
  const text = () => element.textContent ?? '';
  const button = (label: string) =>
    [...element.querySelectorAll('button')].find((b) => b.textContent?.trim() === label);
  const select = (id: string, value: string) => {
    const field = element.querySelector<HTMLSelectElement>(`#${id}`)!;
    field.value = value;
    field.dispatchEvent(new Event('change'));
  };
  const type = (id: string, value: string) => {
    const field = element.querySelector<HTMLInputElement>(`#${id}`)!;
    field.value = value;
    field.dispatchEvent(new Event('input'));
  };
  const loaded = async (rules: Rule[]) => {
    http.expectOne(`${API}/v1/rules?include_inactive=false`).flush(rules);
    http.expectOne(`${API}/v1/zones?include_inactive=false`).flush([CHOSICA]);
    http.expectOne(`${API}/v1/stations?include_inactive=true`).flush([BRIDGE, ELSEWHERE]);
    if (permissions.includes('rules:manage')) {
      http
        .expectOne(`${API}/v1/escalation-policies`)
        .flush([{ id: 'p1', name: 'Protocolo Rímac' }]);
    }
    await fixture.whenStable();
  };
  return { fixture, http, element, text, button, select, type, loaded };
}

describe('RulesPage', () => {
  beforeEach(() => vi.spyOn(window, 'confirm').mockReturnValue(true));
  afterEach(() => vi.restoreAllMocks());

  it('has no serious accessibility violations in the list or the form', async () => {
    const { fixture, element, button, loaded } = setup(MANAGE);
    await loaded([THRESHOLD, SILENCE]);
    expect(await seriousViolations(element)).toEqual([]);
    button('Nueva regla')?.click();
    await fixture.whenStable();
    expect(await seriousViolations(element)).toEqual([]);
  });

  it('lists the rules by zone, in words, and shows a viewer no action', async () => {
    const { text, button, loaded } = setup(['view']);
    await loaded([THRESHOLD, SILENCE]);
    expect(text()).toContain('2 reglas activas en 1 zona');
    expect(text()).toContain('Zona Chosica');
    expect(text()).toContain('Mayor que 3.5 m durante 2 lecturas seguidas');
    expect(text()).toContain('Toda la zona');
    expect(text()).toContain('Política: Protocolo Rímac · Espera 30 min tras resolver');
    expect(button('Nueva regla')).toBeUndefined();
    expect(button('Editar')).toBeUndefined();
  });

  it('creates a threshold rule on a station of the zone, in seconds of cooldown', async () => {
    const { fixture, http, element, text, button, select, type, loaded } = setup(MANAGE);
    await loaded([]);
    button('Nueva regla')?.click();
    await fixture.whenStable();
    select('rule-zone', 'z1');
    await fixture.whenStable();
    const options = [...element.querySelectorAll('#rule-station option')].map((o) =>
      o.textContent?.trim(),
    );
    expect(options).toEqual(['Elige una estación', 'RIM-CHO-01 · Estación RIM-CHO-01 (m)']); // only Chosica's
    select('rule-station', 's1');
    select('rule-operator', 'ge');
    type('rule-value', '4.2');
    type('rule-cooldown', '15');
    button('Guardar')?.click();

    const request = http.expectOne({ method: 'POST', url: `${API}/v1/rules` });
    expect(request.request.body).toEqual({
      type: 'threshold',
      zone_id: 'z1',
      station_id: 's1',
      params: { operator: 'ge', value: 4.2, consecutive: 2 },
      severity: 'warning',
      escalation_policy_id: 'p1',
      cooldown_s: 900,
      is_active: true,
    });
    request.flush(THRESHOLD);
    http.expectOne(`${API}/v1/rules?include_inactive=false`).flush([THRESHOLD]);
    await fixture.whenStable();
    expect(text()).toContain('Regla de RIM-CHO-01 creada.');
  });

  it('marks what is missing before asking the API', async () => {
    const { fixture, http, element, button, loaded } = setup(MANAGE);
    await loaded([]);
    button('Nueva regla')?.click();
    await fixture.whenStable();
    button('Guardar')?.click();
    await fixture.whenStable();
    http.expectNone({ method: 'POST', url: `${API}/v1/rules` });
    expect(element.querySelector('#rule-zone-error')?.textContent).toContain('Elige la zona.');
    expect(element.querySelector('#rule-value-error')?.textContent).toContain(
      'Escribe el valor límite.',
    );
    expect(element.querySelector('#rule-zone')?.getAttribute('aria-describedby')).toBe(
      'rule-zone-error',
    );
  });

  it('shows the API explanation next to its field', async () => {
    const { fixture, http, element, button, select, type, loaded } = setup(MANAGE);
    await loaded([]);
    button('Nueva regla')?.click();
    await fixture.whenStable();
    select('rule-zone', 'z1');
    await fixture.whenStable(); // the zone's stations appear
    select('rule-station', 's1');
    type('rule-value', '4');
    button('Guardar')?.click();
    http.expectOne({ method: 'POST', url: `${API}/v1/rules` }).flush(
      {
        detail: [
          {
            loc: ['body', 'station_id'],
            msg: 'La estación no pertenece a esa zona.',
            type: 'value_error',
          },
        ],
      },
      { status: 422, statusText: 'Unprocessable' },
    );
    await fixture.whenStable();
    expect(element.querySelector('#rule-station-error')?.textContent).toContain(
      'no pertenece a esa zona',
    );
  });

  it('edits a silence rule without letting its type change', async () => {
    const { fixture, http, element, text, button, loaded } = setup(MANAGE);
    await loaded([SILENCE]);
    button('Editar')?.click();
    await fixture.whenStable();
    // The type is disabled while editing: the form must still show the silence fields.
    expect(element.querySelector<HTMLSelectElement>('#rule-type')?.disabled).toBe(true);
    expect(text()).toContain('El tipo no se cambia');
    expect(text()).toContain('Cada estación de la zona se considera sin reportar');
    expect(element.querySelector('#rule-value')).toBeNull();
    button('Guardar')?.click();
    const request = http.expectOne({ method: 'PUT', url: `${API}/v1/rules/r2` });
    expect(request.request.body).toMatchObject({ type: 'silence', station_id: null, params: {} });
  });

  it('previews the draft over the last 24 h with a mark per incident it would have opened', async () => {
    const { fixture, http, text, button, select, type, loaded } = setup(MANAGE);
    await loaded([]);
    button('Nueva regla')?.click();
    await fixture.whenStable();
    select('rule-zone', 'z1');
    await fixture.whenStable(); // the zone's stations appear
    select('rule-station', 's1');
    type('rule-value', '3.5');
    button('Vista previa (24 h)')?.click();

    const request = http.expectOne({ method: 'POST', url: `${API}/v1/rules/preview` });
    expect(request.request.body).toEqual({
      type: 'threshold',
      zone_id: 'z1',
      station_id: 's1',
      params: { operator: 'gt', value: 3.5, consecutive: 2 },
    });
    const preview: RulePreview = {
      since: '2026-10-01T18:00:00Z',
      until: '2026-10-02T18:00:00Z',
      stations: [
        {
          station: { id: 's1', code: 'RIM-CHO-01', name: 'Puente', unit: 'm' },
          readings: [
            { measured_at: '2026-10-02T10:00:00Z', value: 3.6 },
            { measured_at: '2026-10-02T10:00:10Z', value: 3.7 },
          ],
          firings: [{ at: '2026-10-02T10:00:10Z', value: 3.7 }],
          truncated: false,
        },
      ],
    };
    request.flush(preview);
    await fixture.whenStable();
    expect(text()).toContain('RIM-CHO-01: Habría abierto 1 incidente en las últimas 24 h.');
    expect(text()).toContain('Umbral: más de 3.5 m'); // the chart's threshold line

    type('rule-value', '9'); // a different draft: that preview no longer applies
    await fixture.whenStable();
    expect(text()).not.toContain('Habría abierto');
  });

  it('deactivates after confirming and reactivates with the same rule', async () => {
    const { fixture, http, element, button, loaded } = setup(MANAGE);
    await loaded([THRESHOLD]);
    button('Desactivar')?.click();
    http.expectOne({ method: 'DELETE', url: `${API}/v1/rules/r1` }).flush(null);
    http.expectOne(`${API}/v1/rules?include_inactive=false`).flush([]);
    await fixture.whenStable();

    element.querySelector<HTMLInputElement>('app-page-header input[type="checkbox"]')!.click();
    http
      .expectOne(`${API}/v1/rules?include_inactive=true`)
      .flush([{ ...THRESHOLD, is_active: false }]);
    await fixture.whenStable();
    expect(element.textContent).toContain('Desactivada');
    button('Reactivar')?.click();
    const request = http.expectOne({ method: 'PUT', url: `${API}/v1/rules/r1` });
    expect(request.request.body).toMatchObject({
      is_active: true,
      cooldown_s: 1800,
      station_id: 's1',
    });
  });
});
