import { DestroyRef, Signal, inject, signal } from '@angular/core';

/**
 * The browser clock as a signal, refreshed every `periodMs`, so relative ages ("hace 12 s")
 * and the reporting/silent state move on their own while live events bring new heartbeats.
 * Call it in an injection context: the timer stops with the component.
 */
export function clock(periodMs: number): Signal<number> {
  const now = signal(Date.now());
  const timer = setInterval(() => now.set(Date.now()), periodMs);
  inject(DestroyRef).onDestroy(() => clearInterval(timer));
  return now.asReadonly();
}
