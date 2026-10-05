// @ts-expect-error the dashboard has no Node types: this test reads index.html
import { readFileSync } from 'node:fs';
import { TestBed } from '@angular/core/testing';
import { useLanguage } from '../i18n/i18n';
import { THEME_STORAGE_KEY, ThemeService } from './theme';
import { ThemePicker } from './theme-picker';

/** A system color scheme the test can change, as the OS does at sunset. */
function fakeSystem(dark: boolean) {
  const listeners: ((event: { matches: boolean }) => void)[] = [];
  const query = {
    matches: dark,
    addEventListener: (_type: string, listener: (event: { matches: boolean }) => void) =>
      listeners.push(listener),
  };
  vi.stubGlobal('matchMedia', () => query);
  return {
    turn(next: boolean): void {
      query.matches = next;
      for (const listener of listeners) listener({ matches: next });
    },
  };
}

const root = document.documentElement;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
  root.classList.remove('dark');
});

describe('ThemeService', () => {
  it('follows the system, also when it changes, until the user picks a theme', () => {
    const system = fakeSystem(false);
    const service = TestBed.inject(ThemeService);
    TestBed.tick();
    expect([service.choice(), service.theme(), root.classList.contains('dark')]).toEqual([
      'system',
      'light',
      false,
    ]);

    system.turn(true);
    TestBed.tick();
    expect([service.theme(), root.classList.contains('dark')]).toEqual(['dark', true]);

    service.choose('light');
    system.turn(false);
    system.turn(true); // the system no longer decides
    TestBed.tick();
    expect([service.theme(), root.classList.contains('dark')]).toEqual(['light', false]);
  });

  it('keeps the choice in this browser, and forgets it on going back to the system', () => {
    fakeSystem(false);
    const service = TestBed.inject(ThemeService);
    service.choose('dark');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
    service.choose('system');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it('starts with the choice stored in this browser', () => {
    fakeSystem(false);
    localStorage.setItem(THEME_STORAGE_KEY, 'dark');
    const service = TestBed.inject(ThemeService);
    expect([service.choice(), service.theme()]).toEqual(['dark', 'dark']);
  });

  it('still works when the browser blocks storage', () => {
    fakeSystem(true);
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const service = TestBed.inject(ThemeService);
    expect(service.theme()).toBe('dark');
    service.choose('light');
    expect(service.theme()).toBe('light');
  });

  it('works where the browser cannot tell the system theme', () => {
    vi.stubGlobal('matchMedia', undefined);
    expect(TestBed.inject(ThemeService).theme()).toBe('light');
  });
});

describe('the theme before the app loads (index.html)', () => {
  const html: string = readFileSync('src/index.html', 'utf8');
  const script = /<script>([\s\S]*?)<\/script>/.exec(html)?.[1] ?? '';

  /** Runs the page's inline script against a stored choice and a system theme. */
  function darkBeforeLoad(stored: string | null, systemDark: boolean): boolean {
    const element = document.createElement('html');
    const run = new Function('localStorage', 'matchMedia', 'document', script);
    run(
      { getItem: (key: string) => (key === THEME_STORAGE_KEY ? stored : null) },
      () => ({ matches: systemDark }),
      { documentElement: element },
    );
    return element.classList.contains('dark');
  }

  it('applies the same rule as ThemeService, with the same storage key', () => {
    expect(darkBeforeLoad(null, true)).toBe(true);
    expect(darkBeforeLoad(null, false)).toBe(false);
    expect(darkBeforeLoad('dark', false)).toBe(true);
    expect(darkBeforeLoad('light', true)).toBe(false);
  });
});

describe('ThemePicker', () => {
  function render() {
    fakeSystem(false);
    const fixture = TestBed.createComponent(ThemePicker);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    const buttons = () => [...element.querySelectorAll('button')];
    return { fixture, element, buttons };
  }

  it('offers the three choices by name, with the current one pressed', () => {
    const { element, buttons } = render();
    expect(element.querySelector('[role="group"]')?.getAttribute('aria-label')).toBe('Tema');
    expect(buttons().map((b) => b.textContent?.trim())).toEqual(['Sistema', 'Claro', 'Oscuro']);
    expect(buttons().map((b) => b.getAttribute('aria-pressed'))).toEqual([
      'true',
      'false',
      'false',
    ]);
  });

  it('switches the theme without redrawing the page', () => {
    const { fixture, buttons } = render();
    const before = buttons()[2];
    before.click();
    fixture.detectChanges();
    TestBed.tick();
    expect(root.classList.contains('dark')).toBe(true);
    expect(buttons()[2].getAttribute('aria-pressed')).toBe('true');
    expect(buttons()[2]).toBe(before); // the same element: nothing was redrawn
  });

  it('speaks the current language', async () => {
    await useLanguage('en');
    const { buttons } = render();
    expect(buttons().map((b) => b.textContent?.trim())).toEqual(['System', 'Light', 'Dark']);
  });
});
