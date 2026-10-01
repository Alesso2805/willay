import { TestBed } from '@angular/core/testing';
import { LoadState, LoadStatus, loadStatus } from './load-state';

describe('loadStatus', () => {
  it('never says "empty" before the list arrives', () => {
    expect(loadStatus(false, false, 0)).toBe('loading');
    expect(loadStatus(true, false, 0)).toBe('empty');
    expect(loadStatus(true, false, 3)).toBe('ready');
    expect(loadStatus(true, true, 3)).toBe('error'); // un error se muestra aunque haya datos viejos
  });
});

describe('LoadState', () => {
  function render(status: LoadStatus) {
    const fixture = TestBed.createComponent(LoadState);
    fixture.componentRef.setInput('status', status);
    fixture.componentRef.setInput('loading', 'Cargando estaciones…');
    fixture.componentRef.setInput('empty', 'Todavía no hay estaciones.');
    fixture.componentRef.setInput('error', 'No se pudieron cargar las estaciones.');
    fixture.detectChanges();
    return { fixture, element: fixture.nativeElement as HTMLElement };
  }

  it('announces loading politely', () => {
    const { element } = render('loading');
    expect(element.querySelector('[role="status"]')?.textContent).toContain('Cargando estaciones…');
  });

  it('shows the empty message', () => {
    expect(render('empty').element.textContent).toContain('Todavía no hay estaciones.');
  });

  it('shows nothing when the list is ready', () => {
    expect(render('ready').element.textContent?.trim()).toBe('');
  });

  it('alerts an error and offers a retry', () => {
    const { fixture, element } = render('error');
    let retried = 0;
    fixture.componentInstance.retry.subscribe(() => retried++);
    const alert = element.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('No se pudieron cargar las estaciones.');
    alert?.querySelector('button')?.click();
    expect(retried).toBe(1);
  });
});
