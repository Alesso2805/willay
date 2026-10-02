import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { IncidentActions } from './incident-actions';
import { IncidentDetail } from './incidents.api';

const URL = `${settings.apiUrl}/v1/incidents/i1`;
const RESPONDER = ['view', 'incidents:acknowledge'];
const OPERATOR = ['view', 'incidents:acknowledge', 'incidents:resolve'];

const OPEN: IncidentDetail = {
  id: 'i1',
  zone_id: 'z1',
  zone_name: 'Chosica',
  station_id: 's1',
  station_code: 'RIM-SEU-01',
  rule_type: 'silence',
  severity: 'critical',
  status: 'open',
  current_level: 2,
  opened_at: '2026-10-02T02:40:39Z',
  escalation_exhausted_at: null,
  trigger_value: 85.6,
  acknowledged_at: null,
  resolved_at: null,
  resolution: null,
  timeline: [],
};

async function setup(permissions: string[], incident: Partial<IncidentDetail> = {}) {
  TestBed.configureTestingModule({
    imports: [IncidentActions],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: Session, useValue: { me: signal({ permissions }) } },
    ],
  });
  const fixture = TestBed.createComponent(IncidentActions);
  fixture.componentRef.setInput('incident', { ...OPEN, ...incident });
  const changed = vi.fn();
  fixture.componentInstance.changed.subscribe(changed);
  await fixture.whenStable();
  const element = fixture.nativeElement as HTMLElement;
  const http = TestBed.inject(HttpTestingController);
  const button = (label: string) =>
    [...element.querySelectorAll('button')].find((b) => b.textContent?.trim() === label);
  const text = () => element.textContent?.replace(/\s+/g, ' ') ?? '';
  return { fixture, element, http, button, text, changed };
}

describe('IncidentActions', () => {
  it('a viewer gets no buttons, and is told why', async () => {
    const { element, text } = await setup(['view']);
    expect(element.querySelectorAll('button')).toHaveLength(0);
    expect(text()).toContain('Tu rol solo permite ver este incidente.');
  });

  it('a responder acknowledges an open incident, but cannot resolve it', async () => {
    const { fixture, http, button, text, changed } = await setup(RESPONDER);
    expect(button('Resolver…')).toBeUndefined();

    button('Confirmar')?.click();
    http.expectOne({ method: 'POST', url: `${URL}/acknowledge` }).flush({ ...OPEN, status: 'acknowledged' });
    await fixture.whenStable();
    expect(changed).toHaveBeenCalledTimes(1);
    expect(text()).toContain('Incidente confirmado.');
  });

  it('a responder is told that resolving an acknowledged incident is for operation', async () => {
    const { element, text } = await setup(RESPONDER, { status: 'acknowledged' });
    expect(element.querySelectorAll('button')).toHaveLength(0);
    expect(text()).toContain('Resolverlo le corresponde a operación');
  });

  it('an operator resolves as a false alarm only after choosing and confirming', async () => {
    const { fixture, element, http, button, text, changed } = await setup(OPERATOR, {
      status: 'acknowledged',
    });
    expect(button('Confirmar')).toBeUndefined(); // already acknowledged

    button('Resolver…')?.click();
    await fixture.whenStable();
    const radios = element.querySelectorAll<HTMLInputElement>('input[type="radio"]');
    expect(document.activeElement).toBe(radios[0]); // the panel takes the focus
    expect(text()).toContain('Resolver es definitivo');
    expect(button('Resolver definitivamente')?.disabled).toBe(true); // nothing chosen yet
    expect(await seriousViolations(element)).toEqual([]);

    radios[1].click(); // Falsa alarma
    await fixture.whenStable();
    button('Resolver definitivamente')?.click();
    const request = http.expectOne({ method: 'POST', url: `${URL}/resolve` });
    expect(request.request.body).toEqual({ resolution: 'false_alarm' });
    request.flush({ ...OPEN, status: 'resolved' });
    await fixture.whenStable();
    expect(changed).toHaveBeenCalledTimes(1);
    expect(text()).toContain('Incidente marcado como falsa alarma.');
    expect(element.querySelector('#resolve-panel')).toBeNull();
  });

  it('cancelling closes the panel without asking the API', async () => {
    const { fixture, element, http, button } = await setup(OPERATOR);
    button('Resolver…')?.click();
    await fixture.whenStable();
    button('Cancelar')?.click();
    await fixture.whenStable();
    expect(element.querySelector('#resolve-panel')).toBeNull();
    http.verify();
  });

  it('explains a 409 and asks to reload when someone got there first', async () => {
    const { fixture, http, button, text, changed } = await setup(OPERATOR);
    button('Confirmar')?.click();
    http
      .expectOne(`${URL}/acknowledge`)
      .flush(
        { detail: 'El incidente ya está confirmado: no se puede confirmar.' },
        { status: 409, statusText: 'Conflict' },
      );
    await fixture.whenStable();
    expect(text()).toContain(
      'El incidente ya está confirmado: no se puede confirmar. Se actualizó el incidente.',
    );
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it('offers no status change on a resolved incident', async () => {
    const { element, text } = await setup(OPERATOR, { status: 'resolved' });
    expect(element.querySelectorAll('button')).toHaveLength(0);
    expect(text()).toContain('ya no admite cambios de estado');
  });
});
