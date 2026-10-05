import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { settings } from '../settings';

/** docs/openapi.json › Phase: where the Rímac story is. */
export type DemoPhase = 'normal' | 'drop' | 'silence' | 'done';

/** docs/openapi.json › DemoRunOut. */
export interface DemoRun {
  id: number;
  kind: 'scenario' | 'restore';
  status: 'queued' | 'running' | 'done' | 'failed';
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** Only while a scenario plays. */
  phase: DemoPhase | null;
  elapsed_s: number | null;
}

/** docs/openapi.json › DemoOut. */
export interface Demo {
  /** The demo is on and this is its organization. */
  available: boolean;
  can_run: boolean;
  duration_s: number;
  timeline: { phase: DemoPhase; at_s: number }[];
  /** The unfinished run, else the latest scenario. */
  run: DemoRun | null;
}

/** The public demo (VIG-43). */
@Injectable({ providedIn: 'root' })
export class DemoApi {
  private readonly http = inject(HttpClient);
  private readonly url = `${settings.apiUrl}/v1/demo`;

  get(): Observable<Demo> {
    return this.http.get<Demo>(this.url);
  }

  /** 409 while a run is in progress. */
  startScenario(): Observable<DemoRun> {
    return this.http.post<DemoRun>(`${this.url}/scenario`, {});
  }
}
