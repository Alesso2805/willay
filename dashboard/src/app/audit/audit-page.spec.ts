import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  TestRequest,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { AuditPage } from './audit-page';
import { AuditEntry } from './audit.api';

const URL = `${settings.apiUrl}/v1/audit`;
const entry = (id: number, changes: Partial<AuditEntry> = {}): AuditEntry => ({
  id,
  at: '2026-10-02T22:03:11Z',
  actor: { id: 'u1', name: 'Óscar Operador Rímac' },
  entity_type: 'rule',
  entity_id: `r${id}`,
  action: 'update',
  before: { zone: 'Chosica', station: 'RIM-CHO-02', cooldown_s: 300 },
  after: { zone: 'Chosica', station: 'RIM-CHO-02', cooldown_s: 600 },
  ...changes,
});

async function setup(permissions = ['view', 'audit:view'], query = '') {
  TestBed.configureTestingModule({
    imports: [AuditPage],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([{ path: 'auditoria', component: AuditPage }]),
      {
        provide: Session,
        useValue: { me: signal({ permissions, organization_timezone: 'America/Lima' }) },
      },
    ],
  });
  await TestBed.inject(Router).navigateByUrl(`/auditoria${query}`);
  const fixture = TestBed.createComponent(AuditPage);
  const http = TestBed.inject(HttpTestingController);
  const element = fixture.nativeElement as HTMLElement;
  const text = () => element.textContent ?? '';
  const button = (label: string) =>
    [...element.querySelectorAll('button')].find((b) => b.textContent?.trim() === label);
  const page = () => http.expectOne((r) => r.url === URL);
  const authors = () =>
    http.expectOne(`${URL}/authors`).flush([{ id: 'u1', name: 'Óscar Operador Rímac' }]);
  return { fixture, http, element, text, button, page, authors };
}

function params(request: TestRequest): Record<string, string> {
  return Object.fromEntries(
    request.request.params.keys().map((k) => [k, request.request.params.get(k)!]),
  );
}

describe('AuditPage', () => {
  it('has no serious accessibility violations', async () => {
    const { fixture, element, page, authors } = await setup();
    authors();
    page().flush({
      items: [
        entry(1),
        entry(2, {
          actor: null,
          entity_type: 'contact',
          action: 'telegram_linked',
          after: { full_name: 'Rosa' },
        }),
      ],
      next_cursor: null,
    });
    await fixture.whenStable();
    expect(await seriousViolations(element)).toEqual([]);
  });

  it('shows when, who, what and each changed field', async () => {
    const { fixture, element, page, authors } = await setup();
    authors();
    page().flush({ items: [entry(1)], next_cursor: null });
    await fixture.whenStable();
    const row = element.querySelector('tbody tr')?.textContent ?? '';
    expect(row).toContain('02/10/2026 17:03:11'); // Lima
    expect(row).toContain('Óscar Operador Rímac');
    expect(row).toContain('Editó la regla Chosica · RIM-CHO-02');
    expect(row).toContain('Espera tras resolver (s):');
    expect(row).toContain('300');
    expect(row).toContain('600');
  });

  it('follows the cursor with "Cargar más" and appends the next page', async () => {
    const { fixture, http, text, button, page, authors } = await setup();
    authors();
    page().flush({ items: [entry(3), entry(2)], next_cursor: 'abc' });
    await fixture.whenStable();
    button('Cargar más')?.click();
    const next = http.expectOne((r) => r.url === URL && r.params.get('cursor') === 'abc');
    next.flush({ items: [entry(1, { action: 'create', before: null })], next_cursor: null });
    await fixture.whenStable();
    expect(text()).toContain('Creó la regla');
    expect(button('Cargar más')).toBeUndefined();
  });

  it('reads its filters from the URL, in the organization days', async () => {
    const { fixture, page, authors } = await setup(
      ['audit:view'],
      '?tipo=rule&autor=u1&desde=2026-10-01&hasta=2026-10-02&entidad=r9',
    );
    authors();
    const request = page();
    expect(params(request)).toEqual({
      entity_type: 'rule',
      actor_id: 'u1',
      entity_id: 'r9',
      since: '2026-10-01T05:00:00.000Z',
      until: '2026-10-03T05:00:00.000Z', // "hasta" includes its whole day
    });
    request.flush({ items: [], next_cursor: null });
    await fixture.whenStable();
    expect(fixture.nativeElement.textContent).toContain('No hay registros con estos filtros.');
    expect(fixture.nativeElement.textContent).toContain('Solo el historial de una entidad.');
  });

  it('changing a filter goes through the URL', async () => {
    const { fixture, http, element, page, authors } = await setup();
    authors();
    page().flush({ items: [], next_cursor: null });
    await fixture.whenStable();
    const type = element.querySelector<HTMLSelectElement>('#audit-type')!;
    type.value = 'station';
    type.dispatchEvent(new Event('change'));
    await fixture.whenStable();
    expect(TestBed.inject(Router).url).toBe('/auditoria?tipo=station');
    http.expectOne((r) => r.url === URL && r.params.get('entity_type') === 'station');
  });

  it('explains to a role without access why it sees nothing, without asking the API', async () => {
    const { fixture, http } = await setup(['view', 'contacts:manage']);
    await fixture.whenStable();
    http.expectNone((r) => r.url.startsWith(URL));
    expect(fixture.nativeElement.textContent).toContain('Tu rol no permite ver la auditoría');
  });
});
