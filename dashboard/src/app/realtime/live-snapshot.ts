import { Signal, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { EMPTY, Subject, catchError, forkJoin, switchMap } from 'rxjs';
import { Incident, IncidentsApi } from '../incidents/incidents.api';
import { Session } from '../session';
import { keepNewerHeartbeats, withHeartbeat } from '../stations/station-presentation';
import { Station, StationsApi } from '../stations/stations.api';
import { clock } from '../ui/clock';
import { Zone, ZonesApi } from '../zones/zones.api';
import { LiveEvents, dataTime } from './live-events';

/** The organization's active incidents, stations and active zones. */
export interface Snapshot {
  incidents: Incident[];
  stations: Station[];
  zones: Zone[];
}

export interface LiveSnapshot {
  data: Signal<Snapshot | null>;
  failed: Signal<boolean>;
  /** The clock, for ages ("hace 12 s"). */
  now: Signal<number>;
  /** What silence is judged against: the clock while live, the newest data otherwise. */
  asOf: Signal<number>;
  load: () => void;
}

/**
 * The snapshot that Home and the live map show, kept current by the live channel: heartbeats
 * update in place; incident events, reconnections and the fallback polling reload it over REST,
 * so the viewer's permissions apply. Call it in an injection context: it lives with the page.
 */
export function liveSnapshot(): LiveSnapshot {
  const live = inject(LiveEvents);
  const session = inject(Session);
  const incidentsApi = inject(IncidentsApi);
  const stationsApi = inject(StationsApi);
  const zonesApi = inject(ZonesApi);

  const data = signal<Snapshot | null>(null);
  const failed = signal(false);
  const now = clock(1_000);
  const syncedAt = signal(Date.now());
  const asOf = computed(() => dataTime(live.status(), now(), syncedAt(), live.lostAt()));

  // switchMap: only the latest snapshot counts, even if an older request answers later.
  const loads = new Subject<void>();
  loads
    .pipe(
      switchMap(() =>
        forkJoin({
          incidents: incidentsApi.list(['open', 'acknowledged']),
          stations: stationsApi.list(),
          zones: zonesApi.list(),
        }).pipe(
          catchError(() => {
            failed.set(true);
            return EMPTY;
          }),
        ),
      ),
      takeUntilDestroyed(),
    )
    .subscribe((fresh) => {
      const stations = keepNewerHeartbeats(fresh.stations, data()?.stations ?? []);
      data.set({ ...fresh, stations });
      syncedAt.set(Date.now());
      failed.set(false);
    });

  // Without the `view` permission the API would refuse every request.
  const load = () => {
    if (session.me()?.permissions.includes('view')) loads.next();
  };
  live.reload$.pipe(takeUntilDestroyed()).subscribe(load);
  live.incidents$.pipe(takeUntilDestroyed()).subscribe(load);
  live.heartbeats$
    .pipe(takeUntilDestroyed())
    .subscribe(({ stationId, heartbeat }) =>
      data.update(
        (current) =>
          current && { ...current, stations: withHeartbeat(current.stations, stationId, heartbeat) },
      ),
    );
  load();

  return { data: data.asReadonly(), failed: failed.asReadonly(), now, asOf, load };
}
