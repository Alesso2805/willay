import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Session } from '../session';
import { settings } from '../settings';
import { seriousViolations } from '../ui/axe';
import { DemoPanel, stopwatch } from './demo-panel';
import { Demo, DemoRun } from './demo.api';

const URL = `${settings.apiUrl}/v1/demo`;
const TIMELINE: Demo['timeline'] = [
  { phase: 'normal', at_s: 0 },
  { phase: 'drop', at_s: 60 },
  { phase: 'silence', at_s: 300 },
  { phase: 'done', at_s: 540 },
];

function demo(overrides: Partial<Demo> = {}): Demo {
  return {
    available: true,
    can_run: true,
    duration_s: 540,
    timeline: TIMELINE,
    run: null,
    ...overrides,
  };
}

function run(overrides: Partial<DemoRun> = {}): DemoRun {
  return {
    id: 1,
    kind: 'scenario',
    status: 'running',
    requested_at: '2026-10-05T15:00:00Z',
    started_at: '2026-10-05T15:00:01Z',
    finished_at: null,
    phase: 'drop',
    elapsed_s: 75,
    ...overrides,
  };
}

function setup() {
  TestBed.configureTestingModule({
    imports: [DemoPanel],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      { provide: Session, useValue: { me: signal({ organization_timezone: 'America/Lima' }) } },
    ],
  });
  const fixture = TestBed.createComponent(DemoPanel);
  const http = TestBed.inject(HttpTestingController);
  const element = fixture.nativeElement as HTMLElement;
  const text = () => element.textContent?.replace(/\s+/g, ' ') ?? '';
  const button = () =>
    [...element.querySelectorAll('button')].find((b) => b.textContent?.includes('Correr'));
  const answer = async (body: Demo) => {
    http.expectOne(URL).flush(body);
    await fixture.whenStable();
  };
  return { fixture, http, element, text, button, answer };
}

describe('DemoPanel', () => {
  it('shows nothing outside the public demo', async () => {
    const { element, answer } = setup();
    await answer(demo({ available: false, can_run: false }));
    expect(element.querySelector('section')).toBeNull();
  });

  it('explains the scenario, links the emails and lets the demo admin start it', async () => {
    const { fixture, http, element, text, button, answer } = setup();
    await answer(demo());
    expect(text()).toContain('Demo pública: el escenario del Rímac');
    expect(element.querySelector('a[target="_blank"]')?.getAttribute('href')).toBe(
      settings.mailUrl,
    );

    button()?.click();
    http.expectOne({ method: 'POST', url: `${URL}/scenario` }).flush(run({ status: 'queued' }));
    await answer(
      demo({ run: run({ status: 'queued', started_at: null, phase: null, elapsed_s: null }) }),
    );
    await fixture.whenStable();
    expect(text()).toContain('Preparando el escenario…');
    expect(button()?.disabled).toBe(true); // one run at a time
  });

  it('says where the story is while it plays, step by step', async () => {
    const { element, text, answer } = setup();
    await answer(demo({ can_run: false, run: run() }));
    expect(text()).toMatch(/En curso: 1:1\d de 9:00/);
    const steps = [...element.querySelectorAll('li')];
    expect(steps.map((s) => s.getAttribute('aria-current'))).toEqual([null, 'step', null, null]);
    expect(steps[0].textContent).toContain('completado');
    expect(steps[1].textContent).toContain('Cae el caudal en Chaclacayo');
    expect(element.querySelector('[aria-live="polite"]')?.textContent).toContain(
      'Cae el caudal en Chaclacayo',
    );
  });

  it('follows a run every 3 s from the moment it starts, not after the idle 30 s', () => {
    vi.useFakeTimers();
    try {
      const { fixture, http, button } = setup();
      http.expectOne(URL).flush(demo());
      fixture.detectChanges();
      button()?.click();
      http.expectOne({ method: 'POST', url: `${URL}/scenario` }).flush(run({ status: 'queued' }));
      const queued = run({ status: 'queued', started_at: null, phase: null, elapsed_s: null });
      http.expectOne(URL).flush(demo({ run: queued }));
      vi.advanceTimersByTime(3_000);
      http.expectOne(URL).flush(demo({ run: run() })); // asked again after 3 s
      vi.advanceTimersByTime(3_000);
      http.expectOne(URL).flush(demo({ run: run({ status: 'done', phase: null }) }));
      vi.advanceTimersByTime(3_000);
      http.expectNone(URL); // nothing playing: back to every 30 s
      vi.advanceTimersByTime(27_000);
      http.expectOne(URL).flush(demo());
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows a viewer the progress but no button', async () => {
    const { button, text, answer } = setup();
    await answer(demo({ can_run: false, run: run() }));
    expect(button()).toBeUndefined();
    expect(text()).toContain('En curso');
  });

  it('explains that another run is in progress', async () => {
    const { fixture, http, text, button, answer } = setup();
    await answer(demo());
    button()?.click();
    http
      .expectOne({ method: 'POST', url: `${URL}/scenario` })
      .flush({ detail: 'busy', code: 'demo_run_active' }, { status: 409, statusText: 'Conflict' });
    await answer(demo({ run: run() }));
    await fixture.whenStable();
    expect(text()).toContain('Ya hay una corrida en curso');
  });

  it('says when the demo is being restored', async () => {
    const { text, answer } = setup();
    await answer(demo({ run: run({ kind: 'restore', phase: null, elapsed_s: null }) }));
    expect(text()).toContain('La demo está volviendo a su estado inicial');
  });

  it('points to the incidents of the last run once it ended', async () => {
    const { text, answer } = setup();
    const ended = run({
      status: 'done',
      finished_at: '2026-10-05T15:09:02Z',
      phase: null,
      elapsed_s: null,
    });
    await answer(demo({ run: ended }));
    expect(text()).toContain('La última corrida terminó el 05/10/2026 10:09');
    expect(text()).toContain('Ver los incidentes que abrió');
  });

  it('has no serious accessibility violations while the story plays', async () => {
    const { element, answer } = setup();
    await answer(demo({ run: run() }));
    expect(await seriousViolations(element)).toEqual([]);
  });
});

describe('stopwatch', () => {
  it('reads minutes and seconds', () => {
    expect([0, 59.9, 75, 540].map(stopwatch)).toEqual(['0:00', '0:59', '1:15', '9:00']);
  });
});
