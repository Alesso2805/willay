import { Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { incidentState } from './incidents/incident-presentation';
import { liveSnapshot } from './realtime/live-snapshot';
import { Session, roleLabels } from './session';
import { stationState } from './stations/station-presentation';
import { Icon } from './ui/icon';
import { Notice } from './ui/notice';
import { PageHeader } from './ui/page-header';

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
          <a routerLink="/incidentes" class="card group p-5 transition hover:ring-brand-600">
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
            <p class="mt-1 text-sm text-slate-500">
              {{ incidentDetail() }}
              <span class="text-brand-700 group-hover:underline">Ver incidentes →</span>
            </p>
          </a>

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
  protected readonly roles = roleLabels;
  private readonly snapshot = liveSnapshot();
  protected readonly summary = this.snapshot.data;
  protected readonly failed = this.snapshot.failed;

  protected readonly activeIncidents = computed(() => this.summary()?.incidents.length ?? 0);
  protected readonly incidentDetail = computed(() => {
    const incidents = this.summary()?.incidents;
    if (!incidents) return 'Cargando…';
    if (incidents.length === 0) return 'Nada que atender ahora.';
    const open = incidents.filter((i) => i.status === 'open').length;
    // The same rule as the map and the inbox: exhausted only while nobody has acknowledged.
    const exhausted = incidents.filter((i) => incidentState(i) === 'exhausted').length;
    const parts = [`${open} sin confirmar`, `${incidents.length - open} confirmados`];
    if (exhausted > 0) parts.push(`${exhausted} con escalamiento agotado`);
    return `${parts.join(' · ')} ·`;
  });
  protected readonly stationCounts = computed(() => {
    const summary = this.summary();
    const asOf = this.snapshot.asOf();
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

  protected load(): void {
    this.snapshot.load();
  }
}
