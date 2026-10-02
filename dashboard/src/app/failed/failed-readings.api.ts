import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { settings } from '../settings';

/** docs/openapi.json › FailedReadingOut: a reading the evaluator gave up on. */
export interface FailedReading {
  /** The queue row: what reprocessing sends back. */
  id: number;
  station_id: string;
  station_code: string;
  station_name: string;
  measured_at: string;
  /** null once the reading itself expired. */
  value: number | null;
  unit: string;
  attempts: number;
  failed_at: string;
  last_error: string | null;
}

@Injectable({ providedIn: 'root' })
export class FailedReadingsApi {
  private readonly http = inject(HttpClient);
  private readonly url = `${settings.apiUrl}/v1/failed-readings`;

  /** Most recent failure first. */
  list(): Observable<FailedReading[]> {
    return this.http.get<FailedReading[]>(this.url);
  }

  count(): Observable<{ count: number }> {
    return this.http.get<{ count: number }>(`${this.url}/count`);
  }

  /** Ids already back in the queue are not counted. */
  reprocess(ids: number[]): Observable<{ reprocessed: number }> {
    return this.http.post<{ reprocessed: number }>(`${this.url}/reprocess`, { ids });
  }
}
