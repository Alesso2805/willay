import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { IncidentComment } from './incident-comment';

const URL = `${settings.apiUrl}/v1/incidents/i1/comments`;

async function setup(permissions: string[]) {
  TestBed.configureTestingModule({
    imports: [IncidentComment],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: Session, useValue: { me: signal({ permissions }) } },
    ],
  });
  const fixture = TestBed.createComponent(IncidentComment);
  fixture.componentRef.setInput('incidentId', 'i1');
  const changed = vi.fn();
  fixture.componentInstance.changed.subscribe(changed);
  await fixture.whenStable();
  const element = fixture.nativeElement as HTMLElement;
  const http = TestBed.inject(HttpTestingController);
  const textarea = () => element.querySelector('textarea') as HTMLTextAreaElement;
  const submit = () => element.querySelector('button[type="submit"]') as HTMLButtonElement;
  const type = async (value: string) => {
    textarea().value = value;
    textarea().dispatchEvent(new Event('input'));
    await fixture.whenStable();
  };
  return { fixture, element, http, textarea, submit, type, changed };
}

describe('IncidentComment', () => {
  it('is not offered to a viewer', async () => {
    const { element } = await setup(['view']);
    expect(element.querySelector('form')).toBeNull();
  });

  it('counts like the API, ignoring surrounding spaces, and needs some text', async () => {
    const { element, submit, type } = await setup(['view', 'incidents:acknowledge']);
    expect(submit().disabled).toBe(true);
    await type('   ');
    expect(submit().disabled).toBe(true);
    await type('  Hola  ');
    expect(element.textContent).toContain('4 de 2000 caracteres');
    expect(submit().disabled).toBe(false);
    expect(await seriousViolations(element)).toEqual([]);
  });

  it('sends the comment without surrounding spaces, then clears and announces it', async () => {
    const { fixture, element, http, textarea, submit, type, changed } = await setup([
      'view',
      'incidents:acknowledge',
    ]);
    await type('  Bajamos a revisar el cauce  ');
    submit().click();
    const request = http.expectOne({ method: 'POST', url: URL });
    expect(request.request.body).toEqual({ text: 'Bajamos a revisar el cauce' });
    request.flush({ id: 9, event_type: 'comment' });
    await fixture.whenStable();
    expect(textarea().value).toBe('');
    expect(element.querySelector('[role="status"]')?.textContent).toContain('Comentario agregado.');
    expect(changed).toHaveBeenCalledTimes(1);
  });

  it('explains a rejected comment and keeps the text', async () => {
    const { fixture, element, http, textarea, submit, type, changed } = await setup([
      'view',
      'incidents:acknowledge',
    ]);
    await type('Hola');
    submit().click();
    http.expectOne(URL).flush({ detail: [] }, { status: 422, statusText: 'Unprocessable' });
    await fixture.whenStable();
    expect(element.textContent).toContain('El comentario debe tener entre 1 y 2000 caracteres.');
    expect(textarea().value).toBe('Hola');
    expect(changed).not.toHaveBeenCalled();
  });
});
