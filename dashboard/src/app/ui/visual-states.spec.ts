import { TestBed } from '@angular/core/testing';
import { contrastRatio } from './contrast';
import { ICONS } from './icon';
import { StateBadge } from './state-badge';
import { ALL_CATALOGS, INCIDENT_STATES, NOTICE_TONES, VisualState } from './visual-states';

const catalogs = Object.entries(ALL_CATALOGS).map(
  ([name, states]) => [name, Object.values(states) as VisualState[]] as const,
);

describe('contrastRatio', () => {
  it('matches the WCAG reference values', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 5);
    expect(contrastRatio('#777777', '#ffffff')).toBeCloseTo(4.48, 2);
    expect(contrastRatio('#ffffff', '#ffffff')).toBe(1);
  });
});

describe.each(catalogs)('visual states: %s', (_name, states) => {
  it('every label is readable on its color (≥ 4.5:1)', () => {
    for (const state of states) {
      expect(contrastRatio(state.foreground, state.background), state.label).toBeGreaterThanOrEqual(
        4.5,
      );
    }
  });

  it('every map color stands out on a light map (≥ 3:1)', () => {
    for (const state of states) {
      expect(contrastRatio(state.map, '#ffffff'), state.label).toBeGreaterThanOrEqual(3);
    }
  });

  it('never relies on color alone: distinct labels and icons', () => {
    expect(new Set(states.map((s) => s.label)).size).toBe(states.length);
    expect(new Set(states.map((s) => s.icon)).size).toBe(states.length);
    for (const state of states) expect(ICONS[state.icon]).toBeDefined();
  });
});

describe('notice tones', () => {
  it('every notice is readable (≥ 4.5:1)', () => {
    for (const [tone, palette] of Object.entries(NOTICE_TONES)) {
      expect(contrastRatio(palette.foreground, palette.background), tone).toBeGreaterThanOrEqual(
        4.5,
      );
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
});
