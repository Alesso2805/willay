import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { Notice } from './notice';

export type LoadStatus = 'loading' | 'error' | 'empty' | 'ready';

/** El estado de una lista según lo que se sabe de ella. */
export function loadStatus(loaded: boolean, failed: boolean, count: number): LoadStatus {
  if (failed) return 'error';
  if (!loaded) return 'loading';
  return count === 0 ? 'empty' : 'ready';
}

/**
 * Carga, vacío y error de una lista con un mismo componente en todas las páginas (VIG-33).
 * Mientras carga no muestra "no hay nada": una lista vacía y una que aún no llegó no son lo
 * mismo para quien está atendiendo una emergencia.
 */
@Component({
  selector: 'app-load-state',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Notice],
  template: `
    @switch (status()) {
      @case ('loading') {
        <p role="status" class="text-sm text-slate-600">{{ loading() }}</p>
      }
      @case ('empty') {
        <p class="text-sm text-slate-600">{{ empty() }}</p>
      }
      @case ('error') {
        <app-notice tone="error">
          {{ error() }}
          <button type="button" class="ml-1 underline" (click)="retry.emit()">Reintentar</button>
        </app-notice>
      }
    }
  `,
})
export class LoadState {
  readonly status = input.required<LoadStatus>();
  readonly loading = input('Cargando…');
  readonly empty = input.required<string>();
  readonly error = input.required<string>();
  readonly retry = output();
}
