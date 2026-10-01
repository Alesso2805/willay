import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { Notice } from './notice';

export type LoadStatus = 'loading' | 'error' | 'empty' | 'ready';

/** A list's state from what is known about it. */
export function loadStatus(loaded: boolean, failed: boolean, count: number): LoadStatus {
  if (failed) return 'error';
  if (!loaded) return 'loading';
  return count === 0 ? 'empty' : 'ready';
}

/**
 * Loading, empty and error states of a list, with the same component on every page (VIG-33).
 * While loading it never says "nothing here": an empty list and one that has not arrived yet
 * are not the same to someone handling an emergency.
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
