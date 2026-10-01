import { TestBed } from '@angular/core/testing';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { EventSourceInit } from 'eventsource';
import { of } from 'rxjs';
import { settings } from '../settings';
import {
  GRACE_MS,
  HeartbeatChange,
  IncidentChange,
  LIVE_SOURCE,
  LiveEvents,
  LiveSource,
  POLL_MS,
  RETRY_FIRST_MS,
} from './live-events';

const CONNECTING = 0;
const CLOSED = 2;

/** An EventSource the test drives: it emits what the server or the library would. */
class FakeSource implements LiveSource {
  static all: FakeSource[] = [];
  readyState = CONNECTING;
  closed = false;
  private readonly listeners = new Map<string, ((event: Event) => void)[]>();

  constructor(
    readonly url: string,
    readonly init: EventSourceInit,
  ) {
    FakeSource.all.push(this);
  }

  addEventListener(type: string, listener: (event: Event) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close(): void {
    this.closed = true;
    this.readyState = CLOSED;
  }

  emit(type: string, data: unknown = {}): void {
    const raw = typeof data === 'string' ? data : JSON.stringify(data);
    this.listeners.get(type)?.forEach((listener) => listener(new MessageEvent(type, { data: raw })));
  }

  /** CONNECTING: the library will retry by itself. CLOSED: it gave up (non-200 answer). */
  fail(readyState: number): void {
    this.readyState = readyState;
    this.listeners.get('error')?.forEach((listener) => listener(new Event('error')));
  }
}

function setup() {
  FakeSource.all = [];
  TestBed.configureTestingModule({
    providers: [
      { provide: OidcSecurityService, useValue: { getAccessToken: () => of('token-123') } },
      {
        provide: LIVE_SOURCE,
        useValue: (url: string, init: EventSourceInit) => new FakeSource(url, init),
      },
    ],
  });
  const live = TestBed.inject(LiveEvents);
  const reloads = vi.fn();
  const incidents: IncidentChange[] = [];
  const heartbeats: HeartbeatChange[] = [];
  live.reload$.subscribe(reloads);
  live.incidents$.subscribe((change) => incidents.push(change));
  live.heartbeats$.subscribe((change) => heartbeats.push(change));
  const source = () => FakeSource.all.at(-1)!;
  return { live, reloads, incidents, heartbeats, source };
}

describe('LiveEvents', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('sends the token in the Authorization header, never in the URL', async () => {
    const fetch = vi.fn(() => Promise.resolve(new Response()));
    vi.stubGlobal('fetch', fetch);
    const { live, source } = setup();
    live.connect();

    expect(source().url).toBe(`${settings.apiUrl}/v1/events`);
    await source().init.fetch!(source().url, {
      headers: { Accept: 'text/event-stream' },
      signal: undefined,
      mode: 'cors',
      cache: 'no-store',
      redirect: 'follow',
    });
    expect(fetch).toHaveBeenCalledWith(
      `${settings.apiUrl}/v1/events`,
      expect.objectContaining({
        headers: { Accept: 'text/event-stream', Authorization: 'Bearer token-123' },
      }),
    );
  });

  it('is live once the server says ready, and then asks pages to reload', () => {
    const { live, reloads, source } = setup();
    live.connect();
    expect(live.status()).toBe('connecting');

    source().emit('ready');
    expect(live.status()).toBe('live');
    expect(reloads).toHaveBeenCalledTimes(1);

    source().emit('resync'); // the server may have dropped a notification
    expect(reloads).toHaveBeenCalledTimes(2);
  });

  it('passes on incident and heartbeat changes and drops malformed ones', () => {
    const { live, incidents, heartbeats, source } = setup();
    live.connect();
    source().emit('ready');

    source().emit('incident', { incident_id: 'i1', event: 'opened' });
    source().emit('incident', { event: 'opened' });
    source().emit('station', {
      station_id: 's1',
      last_seen_at: '2026-10-01T12:00:05.123456+00:00',
      last_measured_at: '2026-10-01T12:00:00+00:00',
      last_value: 83.2,
    });
    source().emit('station', { station_id: 's1', last_value: 'high' });
    source().emit('station', 'not json');

    expect(incidents).toEqual([{ incidentId: 'i1', event: 'opened' }]);
    expect(heartbeats).toEqual([
      {
        stationId: 's1',
        heartbeat: {
          last_seen_at: '2026-10-01T12:00:05.123456+00:00',
          last_measured_at: '2026-10-01T12:00:00+00:00',
          last_value: 83.2,
        },
      },
    ]);
  });

  it('stays live through a short reconnect, such as the one at token expiry', () => {
    const { live, source } = setup();
    live.connect();
    source().emit('ready');

    source().fail(CONNECTING); // the server closed the stream; the library reconnects
    vi.advanceTimersByTime(GRACE_MS - 1);
    expect(live.status()).toBe('live');
    source().emit('ready');
    vi.advanceTimersByTime(GRACE_MS);
    expect(live.status()).toBe('live');
    expect(FakeSource.all).toHaveLength(1);
  });

  it('says the channel is down when a reconnect takes longer than the grace period', () => {
    const { live, source } = setup();
    live.connect();
    source().emit('ready');

    source().fail(CONNECTING);
    vi.advanceTimersByTime(GRACE_MS);
    expect(live.status()).toBe('reconnecting');
    source().emit('ready');
    expect(live.status()).toBe('live');
  });

  it('opens a new connection when the library gives up, waiting longer each time', () => {
    const { live, source } = setup();
    live.connect();

    source().fail(CLOSED); // e.g. a 401 while the token is being renewed
    expect(live.status()).toBe('reconnecting');
    vi.advanceTimersByTime(RETRY_FIRST_MS - 1);
    expect(FakeSource.all).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSource.all).toHaveLength(2);

    source().fail(CLOSED);
    vi.advanceTimersByTime(2 * RETRY_FIRST_MS - 1);
    expect(FakeSource.all).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeSource.all).toHaveLength(3);

    source().emit('ready'); // a good connection resets the wait
    source().fail(CLOSED);
    vi.advanceTimersByTime(RETRY_FIRST_MS);
    expect(FakeSource.all).toHaveLength(4);
    expect(FakeSource.all.slice(0, 3).every((s) => s.closed)).toBe(true);
  });

  it('ignores a connection it already replaced', () => {
    const { live, reloads, source } = setup();
    live.connect();
    const first = source();
    first.fail(CLOSED);
    vi.advanceTimersByTime(RETRY_FIRST_MS);

    first.emit('ready');
    expect(live.status()).toBe('reconnecting');
    expect(reloads).not.toHaveBeenCalled();
  });

  it('asks for a reload every 15 s while the channel is down, and stops once live', () => {
    const { live, reloads, source } = setup();
    live.connect();

    vi.advanceTimersByTime(POLL_MS);
    expect(reloads).toHaveBeenCalledTimes(1);
    source().emit('ready');
    expect(reloads).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(4 * POLL_MS);
    expect(reloads).toHaveBeenCalledTimes(2);
  });

  it('disconnect closes the connection and stops every timer', () => {
    const { live, reloads, source } = setup();
    live.connect();
    source().fail(CLOSED);

    live.disconnect();
    vi.advanceTimersByTime(10 * POLL_MS);
    expect(live.status()).toBe('off');
    expect(FakeSource.all).toHaveLength(1);
    expect(source().closed).toBe(true);
    expect(reloads).not.toHaveBeenCalled();
  });
});
