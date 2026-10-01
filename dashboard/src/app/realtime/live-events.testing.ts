import { signal } from '@angular/core';
import { Subject } from 'rxjs';
import { HeartbeatChange, IncidentChange, LiveEvents, LiveStatus } from './live-events';

/** Stand-in for the live channel in page tests: the test pushes the events itself. */
export class FakeLiveEvents {
  readonly status = signal<LiveStatus>('live');
  readonly reload$ = new Subject<void>();
  readonly incidents$ = new Subject<IncidentChange>();
  readonly heartbeats$ = new Subject<HeartbeatChange>();
  readonly connect = () => this.status.set('connecting');
  readonly disconnect = () => this.status.set('off');
}

export function provideFakeLiveEvents(fake = new FakeLiveEvents()) {
  return { provide: LiveEvents, useValue: fake };
}
