import { Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { t } from './i18n/i18n';
import { DemoPanel } from './demo/demo-panel';
import { incidentState } from './incidents/incident-presentation';
import { liveSnapshot } from './realtime/live-snapshot';
import { Session, roleLabels } from './session';
import { stationState } from './stations/station-presentation';
import { Icon } from './ui/icon';
import { Notice } from './ui/notice';
import { PageHeader } from './ui/page-header';
import { ZONE_STATES } from './ui/visual-states';

/** Home: what an operator wants to know on opening the dashboard, and who they are in Willay. */
@Component({
  selector: 'app-home-page',
  imports: [RouterLink, Icon, Notice, PageHeader, DemoPanel],
  template: `
    @if (session.me(); as me) {
      <app-page-header
        [title]="t('home.title')"
        [subtitle]="
          t('home.subtitle', {
            organization: me.organization_name,
            timezone: me.organization_timezone,
          })
        "
      />

      @if (me.permissions.length === 0) {
        <!-- SPEC: without roles only /v1/me is allowed, so the dashboard explains why nothing shows. -->
        <app-notice tone="info" class="mb-6">
          <p class="font-semibold">{{ t('home.noRoleTitle') }}</p>
          <p class="mt-1">{{ t('home.noRoleBody') }}</p>
        </app-notice>
      } @else {
        @if (failed()) {
          <app-notice class="mb-6">
            {{ t('home.loadFailed') }}
            <button type="button" class="ml-1 underline" (click)="load()">
              {{ t('ui.retry') }}
            </button>
          </app-notice>
        }
        <app-demo-panel />
        <section [attr.aria-label]="t('home.title')" class="mb-6 grid gap-4 md:grid-cols-3">
          <a routerLink="/incidentes" class="card group p-5 transition hover:ring-brand-600">
            <div class="flex items-center gap-3">
              <span
                class="grid size-10 place-items-center rounded-lg"
                [style.color]="incidentLook().foreground"
                [style.background-color]="incidentLook().background"
              >
                <app-icon [name]="activeIncidents() > 0 ? 'bell' : 'check'" [size]="20" />
              </span>
              <h2 class="text-sm font-medium text-ink-muted">{{ t('home.incidentsTitle') }}</h2>
            </div>
            <p class="mt-4 text-3xl font-semibold tabular-nums text-ink">
              {{ summary() ? activeIncidents() : '—' }}
            </p>
            <p class="mt-1 text-sm text-ink-subtle">
              {{ incidentDetail() }}
              <span class="text-accent group-hover:underline">{{ t('home.incidentsLink') }}</span>
            </p>
          </a>

          <a routerLink="/estaciones" class="card group p-5 transition hover:ring-brand-600">
            <div class="flex items-center gap-3">
              <span class="grid size-10 place-items-center rounded-lg bg-accent-soft text-accent">
                <app-icon name="antenna" [size]="20" />
              </span>
              <h2 class="text-sm font-medium text-ink-muted">{{ t('home.stationsTitle') }}</h2>
            </div>
            <p class="mt-4 text-3xl font-semibold tabular-nums text-ink">
              {{
                summary()
                  ? t('home.stationsReporting', {
                      reporting: stationCounts().reporting,
                      total: stationCounts().total,
                    })
                  : '—'
              }}
            </p>
            <p class="mt-1 text-sm text-ink-subtle">
              {{ stationDetail() }}
              <span class="text-accent group-hover:underline">{{ t('home.stationsLink') }}</span>
            </p>
          </a>

          <a routerLink="/zonas" class="card group p-5 transition hover:ring-brand-600">
            <div class="flex items-center gap-3">
              <span class="grid size-10 place-items-center rounded-lg bg-accent-soft text-accent">
                <app-icon name="map" [size]="20" />
              </span>
              <h2 class="text-sm font-medium text-ink-muted">{{ t('home.zonesTitle') }}</h2>
            </div>
            <p class="mt-4 text-3xl font-semibold tabular-nums text-ink">
              {{ summary() ? summary()!.zones.length : '—' }}
            </p>
            <p class="mt-1 text-sm text-ink-subtle">
              {{ zoneDetail() }}
              <span class="text-accent group-hover:underline">{{ t('home.zonesLink') }}</span>
            </p>
          </a>
        </section>
      }

      <section class="card p-5" aria-labelledby="profile-title">
        <h2 id="profile-title" class="font-semibold text-ink">{{ t('home.accountTitle') }}</h2>
        <dl class="mt-4 grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
          <div>
            <dt class="text-ink-subtle">{{ t('home.email') }}</dt>
            <dd class="mt-0.5 font-medium break-words text-ink">{{ me.email }}</dd>
          </div>
          <div>
            <dt class="text-ink-subtle">{{ t('home.organization') }}</dt>
            <dd class="mt-0.5 font-medium text-ink">{{ me.organization_name }}</dd>
          </div>
          <div>
            <dt class="text-ink-subtle">{{ t('home.timezone') }}</dt>
            <dd class="mt-0.5 font-medium text-ink">{{ me.organization_timezone }}</dd>
          </div>
          <div>
            <dt class="text-ink-subtle">{{ t('home.roles') }}</dt>
            <dd class="mt-0.5 font-medium text-ink">{{ roles(me.roles) }}</dd>
          </div>
        </dl>
      </section>
    }
  `,
})
export class HomePage {
  protected readonly session = inject(Session);
  protected readonly roles = roleLabels;
  protected readonly t = t;
  private readonly snapshot = liveSnapshot();
  protected readonly summary = this.snapshot.data;
  protected readonly failed = this.snapshot.failed;

  protected readonly activeIncidents = computed(() => this.summary()?.incidents.length ?? 0);
  /** Orange while something is open, green when all is calm: the colors of a zone on the map. */
  protected readonly incidentLook = computed(() =>
    this.activeIncidents() > 0 ? ZONE_STATES.open : ZONE_STATES.calm,
  );
  protected readonly incidentDetail = computed(() => {
    const incidents = this.summary()?.incidents;
    if (!incidents) return t('ui.loading');
    if (incidents.length === 0) return t('home.incidentsNone');
    const open = incidents.filter((i) => i.status === 'open').length;
    // The same rule as the map and the inbox: exhausted only while nobody has acknowledged.
    const exhausted = incidents.filter((i) => incidentState(i) === 'exhausted').length;
    const parts = [
      t('home.unacknowledged', { count: open }),
      t('home.acknowledged', { count: incidents.length - open }),
    ];
    if (exhausted > 0) parts.push(t('home.exhausted', { count: exhausted }));
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
    if (!this.summary()) return t('ui.loading');
    const { silent, unzoned } = this.stationCounts();
    return `${t('home.stationsDetail', { silent, unzoned })} ·`;
  });
  protected readonly zoneDetail = computed(() => {
    const zones = this.summary()?.zones;
    if (!zones) return t('ui.loading');
    const critical = zones.filter((z) => z.risk_level === 'critical').length;
    const high = zones.filter((z) => z.risk_level === 'high').length;
    return `${t('home.zonesDetail', { critical, high })} ·`;
  });

  protected load(): void {
    this.snapshot.load();
  }
}
