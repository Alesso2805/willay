// @ts-expect-error the dashboard has no Node types: only this test reads a file
import { readFileSync } from 'node:fs';
import { TestBed } from '@angular/core/testing';
import { LANGUAGES, t, useLanguage } from '../i18n/i18n';
import { contrastRatio } from './contrast';
import { ICONS } from './icon';
import { StateBadge } from './state-badge';
import {
  ALL_CATALOGS,
  INCIDENT_STATES,
  NOTICE_TONES,
  NoticeTone,
  Tone,
  VisualState,
  toneClass,
} from './visual-states';

const catalogs = Object.entries(ALL_CATALOGS).map(
  ([name, states]) => [name, Object.values(states) as VisualState[]] as const,
);

type Theme = 'light' | 'dark';
const THEMES: readonly Theme[] = ['light', 'dark'];

/**
 * The colors each theme defines in styles.css (VIG-41): light ones in `@theme` and `:root`,
 * dark ones overriding them in `:root.dark`. Tests measure what the browser paints.
 */
function themeColors(): { light: Record<string, string>; darkOwn: Record<string, string> } {
  const css: string = readFileSync('src/styles.css', 'utf8');
  const light: Record<string, string> = {};
  const darkOwn: Record<string, string> = {};
  for (const [, selector, body] of css.matchAll(/(@theme|:root\.dark|:root)\s*\{([^{}]*)\}/g)) {
    const target = selector === ':root.dark' ? darkOwn : light;
    for (const [, name, value] of body.matchAll(/(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/g)) {
      target[name] = value;
    }
  }
  return { light, darkOwn };
}

const { light: LIGHT, darkOwn: DARK_OWN } = themeColors();
const COLORS: Record<Theme, Record<string, string>> = {
  light: LIGHT,
  dark: { ...LIGHT, ...DARK_OWN },
};

function color(theme: Theme, name: string): string {
  const value = COLORS[theme][name];
  if (!value) throw new Error(`${name} is not defined for the ${theme} theme`);
  return value;
}

function tone(theme: Theme, name: Tone, part: 'fg' | 'bg' | 'map'): string {
  return color(theme, `--tone-${name}-${part}`);
}

describe('contrastRatio', () => {
  it('matches the WCAG reference values', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 5);
    expect(contrastRatio('#777777', '#ffffff')).toBeCloseTo(4.48, 2);
    expect(contrastRatio('#ffffff', '#ffffff')).toBe(1);
  });
});

describe('theme colors', () => {
  it('the dark theme sets every semantic color and tone itself, none inherited by mistake', () => {
    const themed = Object.keys(LIGHT).filter(
      (name) => !name.startsWith('--color-night') && !name.startsWith('--color-brand'),
    );
    expect(themed.length).toBeGreaterThan(40);
    for (const name of themed) expect(DARK_OWN[name], name).toBeDefined();
  });

  describe.each(THEMES)('%s theme', (theme) => {
    it('every text color reads ≥ 4.5:1 on every background', () => {
      const texts = ['ink', 'ink-soft', 'ink-muted', 'ink-subtle', 'accent', 'accent-strong'];
      for (const text of [...texts, 'danger', 'danger-strong', 'warning']) {
        for (const background of ['canvas', 'surface', 'surface-muted']) {
          const ratio = contrastRatio(
            color(theme, `--color-${text}`),
            color(theme, `--color-${background}`),
          );
          expect(ratio, `${text} on ${background}`).toBeGreaterThanOrEqual(4.5);
        }
      }
    });

    it('a selected item reads ≥ 4.5:1 on its highlight', () => {
      for (const text of ['ink', 'accent', 'accent-strong']) {
        const ratio = contrastRatio(
          color(theme, `--color-${text}`),
          color(theme, '--color-accent-soft'),
        );
        expect(ratio, text).toBeGreaterThanOrEqual(4.5);
      }
    });
  });
});

describe.each(catalogs)('visual states: %s', (_name, states) => {
  it.each(THEMES)('every label is readable on its color (≥ 4.5:1), %s theme', (theme) => {
    for (const state of states) {
      const ratio = contrastRatio(tone(theme, state.tone, 'fg'), tone(theme, state.tone, 'bg'));
      expect(ratio, state.labelKey).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(THEMES)(
    'every map color stands out on the map and under a white icon (≥ 3:1), %s theme',
    (theme) => {
      for (const state of states) {
        const map = tone(theme, state.tone, 'map');
        expect(
          contrastRatio(map, color(theme, '--map-canvas')),
          state.labelKey,
        ).toBeGreaterThanOrEqual(3);
        expect(contrastRatio(map, '#ffffff'), state.labelKey).toBeGreaterThanOrEqual(3);
      }
    },
  );

  it('paints with CSS variables, so the theme switches without redrawing', () => {
    for (const state of states) {
      expect(state.foreground).toBe(`var(--tone-${state.tone}-fg)`);
      expect(state.map).toBe(`var(--tone-${state.tone}-map)`);
      expect(toneClass(state)).toBe(`tone-${state.tone}`);
    }
  });

  it.each(LANGUAGES)(
    'never relies on color alone: distinct labels (%s) and icons',
    async (language) => {
      await useLanguage(language);
      expect(new Set(states.map((s) => t(s.labelKey))).size).toBe(states.length);
      expect(new Set(states.map((s) => s.icon)).size).toBe(states.length);
      for (const state of states) expect(ICONS[state.icon]).toBeDefined();
    },
  );
});

describe('notice tones', () => {
  it.each(THEMES)('every notice is readable (≥ 4.5:1), %s theme', (theme) => {
    for (const name of Object.keys(NOTICE_TONES) as NoticeTone[]) {
      const ratio = contrastRatio(
        color(theme, `--notice-${name}-fg`),
        color(theme, `--notice-${name}-bg`),
      );
      expect(ratio, name).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe('StateBadge', () => {
  it('shows the label with a decorative icon', () => {
    const fixture = TestBed.createComponent(StateBadge);
    fixture.componentRef.setInput('state', INCIDENT_STATES.exhausted);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    expect(element.textContent?.trim()).toBe('Escalamiento agotado');
    expect(element.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
  });

  it('speaks the current language', async () => {
    await useLanguage('en');
    const fixture = TestBed.createComponent(StateBadge);
    fixture.componentRef.setInput('state', INCIDENT_STATES.exhausted);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent?.trim()).toBe('Escalation exhausted');
  });
});
