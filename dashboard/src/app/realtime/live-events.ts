import { Injectable, InjectionToken, inject, signal } from '@angular/core';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { EventSource, EventSourceInit } from 'eventsource';
import { Subject, firstValueFrom } from 'rxjs';
import { settings } from '../settings';
import { Heartbeat } from '../stations/stations.api';

/** `off`: no session with the `view` permission, so no channel. */
export type LiveStatus = 'off' | 'connecting' | 'live' | 'reconnecting';

export interface IncidentChange {
  incidentId: string;
  /** incident_events.event_type: opened, acknowledged, escalated... */
  event: string;
}

export interface HeartbeatChange {
  stationId: string;
  heartbeat: Heartbeat;
}

/** The part of an EventSource the service uses, so tests can drive a fake one. */
export interface LiveSource {
  readonly readyState: number;
  addEventListener(type: string, listener: (event: Event) => void): void;
  close(): void;
}

export const LIVE_SOURCE = new InjectionToken<
  (url: string, init: EventSourceInit) => LiveSource
>('LIVE_SOURCE', { providedIn: 'root', factory: () => (url, init) => new EventSource(url, init) });

/** First retry after the library gives up; it doubles up to the maximum. */
export const RETRY_FIRST_MS = 2_000;
export const RETRY_MAX_MS = 30_000;
/** The server closes the stream when the token expires and the library reconnects in ~2 s:
 * only a longer gap counts as lost, so the header does not flicker every few minutes. */
export const GRACE_MS = 5_000;
/** Fallback polling while the channel is down, as the workers poll when NOTIFY fails. */
export const POLL_MS = 15_000;

/**
 * The organization's live channel (`GET /v1/events`): one connection per session.
 *
 * Pages reload over REST on `reload$`, which fires on every (re)connection (`ready`: what
 * happened while disconnected is never lost), when the server may have dropped a notification
 * (`resync`), and every 15 s while the channel is down. Incident events only say what changed:
 * pages refetch it over REST, so the viewer's permissions apply. Heartbeats carry their values.
 * `failedReadings$` only says that the set of readings that failed evaluation changed.
 */
@Injectable({ providedIn: 'root' })
export class LiveEvents {
  private readonly oidc = inject(OidcSecurityService);
  private readonly createSource = inject(LIVE_SOURCE);

  private readonly _status = signal<LiveStatus>('off');
  readonly status = this._status.asReadonly();
  /** When the channel last stopped delivering changes; null if it never was live. */
  private readonly _lostAt = signal<number | null>(null);
  readonly lostAt = this._lostAt.asReadonly();

  private readonly reloads = new Subject<void>();
  private readonly incidentChanges = new Subject<IncidentChange>();
  private readonly heartbeatChanges = new Subject<HeartbeatChange>();
  private readonly failedReadingChanges = new Subject<void>();
  readonly reload$ = this.reloads.asObservable();
  readonly incidents$ = this.incidentChanges.asObservable();
  readonly heartbeats$ = this.heartbeatChanges.asObservable();
  readonly failedReadings$ = this.failedReadingChanges.asObservable();

  private source?: LiveSource;
  private retryDelay = RETRY_FIRST_MS;
  private retryTimer?: ReturnType<typeof setTimeout>;
  private graceTimer?: ReturnType<typeof setTimeout>;
  private pollTimer?: ReturnType<typeof setInterval>;

  connect(): void {
    if (this._status() !== 'off') return;
    this.setStatus('connecting');
    this.open();
  }

  disconnect(): void {
    clearTimeout(this.retryTimer);
    clearTimeout(this.graceTimer);
    this.graceTimer = undefined;
    this.source?.close();
    this.source = undefined;
    this.setStatus('off');
  }

  private open(): void {
    const source = this.createSource(`${settings.apiUrl}/v1/events`, {
      // The JWT goes in the header, never in the URL (SPEC). It is read on every connection,
      // so the library's own reconnects carry the token the OIDC client renewed meanwhile.
      fetch: async (url, init) => {
        const token = await firstValueFrom(this.oidc.getAccessToken());
        return fetch(url, { ...init, headers: { ...init.headers, Authorization: `Bearer ${token}` } });
      },
    });
    const on = (type: string, handler: (event: Event) => void) =>
      source.addEventListener(type, (event) => {
        if (source === this.source) handler(event); // a replaced source no longer counts
      });

    on('ready', () => {
      this.retryDelay = RETRY_FIRST_MS;
      clearTimeout(this.graceTimer);
      this.graceTimer = undefined;
      this.setStatus('live');
      this.reloads.next();
    });
    on('resync', () => this.reloads.next());
    on('incident', (event) => {
      const change = incidentChange(event);
      if (change) this.incidentChanges.next(change);
    });
    on('station', (event) => {
      const change = heartbeatChange(event);
      if (change) this.heartbeatChanges.next(change);
    });
    on('failed_readings', () => this.failedReadingChanges.next());
    on('error', () => this.failed(source));
    this.source = source;
  }

  private failed(source: LiveSource): void {
    if (this._status() === 'live') {
      if (this.graceTimer === undefined) {
        this._lostAt.set(Date.now());
        this.graceTimer = setTimeout(() => this.setStatus('reconnecting'), GRACE_MS);
      }
    } else {
      this.setStatus('reconnecting');
    }
    // CONNECTING: the library retries on its own (network error, stream closed at token
    // expiry). CLOSED: it gave up for good on a non-200 answer, e.g. a 401 while the token is
    // being renewed, so the service opens a new connection itself, waiting longer each time.
    if (source.readyState === EventSource.CLOSED) {
      source.close();
      this.retryTimer = setTimeout(() => this.open(), this.retryDelay);
      this.retryDelay = Math.min(this.retryDelay * 2, RETRY_MAX_MS);
    }
  }

  private setStatus(status: LiveStatus): void {
    this._status.set(status);
    const polling = status === 'connecting' || status === 'reconnecting';
    if (polling && this.pollTimer === undefined) {
      this.pollTimer = setInterval(() => this.reloads.next(), POLL_MS);
    } else if (!polling && this.pollTimer !== undefined) {
      clearInterval(this.pollTimer);
      this.pollTimer = undefined;
    }
  }
}

/**
 * The moment a page's data is complete up to, to judge whether a station went silent: now while
 * the channel is live; otherwise the newest of its last REST reload and the moment the channel
 * was lost. A dashboard that lost contact must not report every station as silent.
 */
export function dataTime(
  status: LiveStatus,
  now: number,
  syncedAt: number,
  lostAt: number | null,
): number {
  return status === 'live' ? now : Math.max(syncedAt, lostAt ?? 0);
}

/** The event's JSON data, or null: an odd event is dropped, as the server drops odd notifications. */
function data(event: Event): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(String((event as MessageEvent).data));
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function incidentChange(event: Event): IncidentChange | null {
  const raw = data(event);
  if (typeof raw?.['incident_id'] !== 'string' || typeof raw['event'] !== 'string') return null;
  return { incidentId: raw['incident_id'], event: raw['event'] };
}

function heartbeatChange(event: Event): HeartbeatChange | null {
  const raw = data(event);
  const value = raw?.['last_value'];
  if (
    typeof raw?.['station_id'] !== 'string' ||
    typeof raw['last_seen_at'] !== 'string' ||
    typeof raw['last_measured_at'] !== 'string' ||
    (typeof value !== 'number' && value !== null)
  ) {
    return null;
  }
  return {
    stationId: raw['station_id'],
    heartbeat: {
      last_seen_at: raw['last_seen_at'],
      last_measured_at: raw['last_measured_at'],
      last_value: value,
    },
  };
}
