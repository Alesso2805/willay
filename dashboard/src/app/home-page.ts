import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { EMPTY, Subject, catchError, forkJoin, switchMap } from 'rxjs';
import { Incident, IncidentsApi } from './incidents/incidents.api';
import { LiveEvents, dataTime } from './realtime/live-events';
import { Session, roleLabels } from './session';
import { keepNewerHeartbeats, stationState, withHeartbeat } from './stations/station-presentation';
import { Station, StationsApi } from './stations/stations.api';
import { clock } from './ui/clock';
import { Icon } from './ui/icon';
import { Notice } from './ui/notice';
import { PageHeader } from './ui/page-header';
import { Zone, ZonesApi } from './zones/zones.api';

interface Summary {
  incidents: Incident[];
  stations: Station[];
  zones: Zone[];
}

/** Home: what an operator wants to know on opening the dashboard, and who they are in Willay. */
@Component({
  selector: 'app-home-page',
  imports: [RouterLink, Icon, Notice, PageHeader],
  template: `
    @if (session.me(); as me) {
      <app-page-header
        title="Resumen"
        [subtitle]="me.organization_name + ' · horas en ' + me.organization_timezone"
      />

      @if (me.permissions.length === 0) {
        <!-- SPEC: without roles only /v1/me is allowed, so the dashboard explains why nothing shows. -->
        <app-notice tone="info" class="mb-6">
          <p class="font-semibold">Tu usuario todavía no tiene un rol en Willay</p>
          <p class="mt-1">
            Por eso no ves zonas, estaciones ni incidentes. Pide a quien administra Willay en tu
            organización que te asigne uno.
          </p>
        </app-notice>
      } @else {
        @if (failed()) {
          <app-notice class="mb-6">
            No se pudo cargar el resumen.
            <button type="button" class="ml-1 underline" (click)="load()">Reintentar</button>
          </app-notice>
        }
        <section aria-label="Resumen" class="mb-6 grid gap-4 md:grid-cols-3">
          <div class="card p-5">
            <div class="flex items-center gap-3">
              <span
                class="grid size-10 place-items-center rounded-lg"
                [class]="
                  activeIncidents() > 0
                    ? 'bg-orange-100 text-orange-800'
                    : 'bg-green-100 text-green-800'
                "
              >
                <app-icon [name]="activeIncidents() > 0 ? 'bell' : 'check'" [size]="20" />
              </span>
              <h2 class="text-sm font-medium text-slate-600">Incidentes activos</h2>
            </div>
            <p class="mt-4 text-3xl font-semibold tabular-nums text-slate-900">
              {{ summary() ? activeIncidents() : '—' }}
            </p>
            <p class="mt-1 text-sm text-slate-500">{{ incidentDetail() }}</p>
          </div>

          <a routerLink="/estaciones" class="card group p-5 transition hover:ring-brand-600">
            <div class="flex items-center gap-3">
              <span class="grid size-10 place-items-center rounded-lg bg-brand-50 text-brand-700">
                <app-icon name="antenna" [size]="20" />
              </span>
              <h2 class="text-sm font-medium text-slate-600">Estaciones reportando</h2>
            </div>
            <p class="mt-4 text-3xl font-semibold tabular-nums text-slate-900">
              {{ summary() ? stationCounts().reporting + ' de ' + stationCounts().total : '—' }}
            </p>
            <p class="mt-1 text-sm text-slate-500">
              {{ stationDetail() }}
              <span class="text-brand-700 group-hover:underline">Ver estaciones →</span>
            </p>
          </a>

          <a routerLink="/zonas" class="card group p-5 transition hover:ring-brand-600">
            <div class="flex items-center gap-3">
              <span class="grid size-10 place-items-center rounded-lg bg-brand-50 text-brand-700">
                <app-icon name="map" [size]="20" />
              </span>
              <h2 class="text-sm font-medium text-slate-600">Zonas de riesgo</h2>
            </div>
            <p class="mt-4 text-3xl font-semibold tabular-nums text-slate-900">
              {{ summary() ? summary()!.zones.length : '—' }}
            </p>
            <p class="mt-1 text-sm text-slate-500">
              {{ zoneDetail() }}
              <span class="text-brand-700 group-hover:underline">Ver mapa →</span>
            </p>
          </a>
        </section>
      }

      <section class="card p-5" aria-labelledby="profile-title">
        <h2 id="profile-title" class="font-semibold text-slate-900">Tu cuenta</h2>
        <dl class="mt-4 grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
          <div>
            <dt class="text-slate-500">Correo</dt>
            <dd class="mt-0.5 font-medium break-words text-slate-900">{{ me.email }}</dd>
          </div>
          <div>
            <dt class="text-slate-500">Organización</dt>
            <dd class="mt-0.5 font-medium text-slate-900">{{ me.organization_name }}</dd>
          </div>
          <div>
            <dt class="text-slate-500">Zona horaria</dt>
            <dd class="mt-0.5 font-medium text-slate-900">{{ me.organization_timezone }}</dd>
          </div>
          <div>
            <dt class="text-slate-500">Roles</dt>
            <dd class="mt-0.5 font-medium text-slate-900">{{ roles(me.roles) }}</dd>
          </div>
        </dl>
      </section>
    }
  `,
})
export class HomePage {
  protected readonly session = inject(Session);
  private readonly incidentsApi = inject(IncidentsApi);
  private readonly stationsApi = inject(StationsApi);
  private readonly zonesApi = inject(ZonesApi);
  private readonly live = inject(LiveEvents);

  protected readonly roles = roleLabels;
  protected readonly summary = signal<Summary | null>(null);
  protected readonly failed = signal(false);
  private readonly now = clock(1_000);
  /** Last successful load: while the channel is down, silence is judged up to here. */
  private readonly syncedAt = signal(Date.now());
  /** switchMap: only the latest summary counts, even if an older request answers later. */
  private readonly loads = new Subject<void>();

  protected readonly activeIncidents = computed(() => this.summary()?.incidents.length ?? 0);
  protected readonly incidentDetail = computed(() => {
    const incidents = this.summary()?.incidents;
    if (!incidents) return 'Cargando…';
    if (incidents.length === 0) return 'Nada que atender ahora.';
    const open = incidents.filter((i) => i.status === 'open').length;
    const exhausted = incidents.filter((i) => i.escalation_exhausted_at !== null).length;
    const parts = [`${open} sin confirmar`, `${incidents.length - open} confirmados`];
    if (exhausted > 0) parts.push(`${exhausted} con escalamiento agotado`);
    return parts.join(' · ');
  });
  protected readonly stationCounts = computed(() => {
    const summary = this.summary();
    const asOf = dataTime(this.live.status(), this.now(), this.syncedAt(), this.live.lostAt());
    const states = (summary?.stations ?? []).map((s) => stationState(s, asOf));
    return {
      total: states.length,
      reporting: states.filter((s) => s === 'reporting').length,
      silent: states.filter((s) => s === 'silent').length,
      unzoned: (summary?.stations ?? []).filter((s) => !s.has_zone).length,
    };
  });
  protected readonly stationDetail = computed(() => {
    if (!this.summary()) return 'Cargando…';
    const { silent, unzoned } = this.stationCounts();
    return `${silent} sin reportar · ${unzoned} sin zona ·`;
  });
  protected readonly zoneDetail = computed(() => {
    const zones = this.summary()?.zones;
    if (!zones) return 'Cargando…';
    const critical = zones.filter((z) => z.risk_level === 'critical').length;
    const high = zones.filter((z) => z.risk_level === 'high').length;
    return `${critical} de riesgo crítico · ${high} alto ·`;
  });

  constructor() {
    this.loads
      .pipe(
        switchMap(() =>
          forkJoin({
            incidents: this.incidentsApi.list(['open', 'acknowledged']),
            stations: this.stationsApi.list(),
            zones: this.zonesApi.list(),
          }).pipe(
            catchError(() => {
              this.failed.set(true);
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((data) => {
        const stations = keepNewerHeartbeats(data.stations, this.summary()?.stations ?? []);
        this.summary.set({ ...data, stations });
        this.syncedAt.set(Date.now());
        this.failed.set(false);
      });
    this.load();

    // An incident event only says that something changed: the summary is fetched again, so
    // the viewer's permissions apply. Heartbeats carry their values and update in place.
    this.live.reload$.pipe(takeUntilDestroyed()).subscribe(() => this.load());
    this.live.incidents$.pipe(takeUntilDestroyed()).subscribe(() => this.load());
    this.live.heartbeats$.pipe(takeUntilDestroyed()).subscribe(({ stationId, heartbeat }) =>
      this.summary.update(
        (summary) =>
          summary && { ...summary, stations: withHeartbeat(summary.stations, stationId, heartbeat) },
      ),
    );
  }

  protected load(): void {
    if (this.session.me()?.permissions.includes('view')) this.loads.next();
  }
}
