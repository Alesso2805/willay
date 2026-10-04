import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { EMPTY, Subject, catchError, switchMap } from 'rxjs';
import { t } from '../i18n/i18n';
import { LiveEvents, dataTime } from '../realtime/live-events';
import { Session } from '../session';
import { clock } from '../ui/clock';
import { ageText, localTime, measurement } from '../ui/formats';
import { Icon } from '../ui/icon';
import { LoadState, loadStatus } from '../ui/load-state';
import { Notice } from '../ui/notice';
import { PageHeader } from '../ui/page-header';
import { StateBadge } from '../ui/state-badge';
import { STATION_STATES } from '../ui/visual-states';
import { Zone, ZonesApi } from '../zones/zones.api';
import { LonLat, StationMap } from './station-map';
import {
  POSITIONS,
  UNITS,
  VARIABLES,
  keepNewerHeartbeats,
  stationProblem,
  stationState,
  withHeartbeat,
  positionLabel,
  variableLabel,
} from './station-presentation';
import {
  IssuedKey,
  Source,
  Station,
  StationInput,
  StationsApi,
  Variable,
  ZonePosition,
} from './stations.api';

type Editing = { kind: 'new' } | { kind: 'edit'; station: Station };

@Component({
  selector: 'app-stations-page',
  imports: [StationMap, ReactiveFormsModule, LoadState, Notice, StateBadge, PageHeader, Icon],
  templateUrl: './stations-page.html',
})
export class StationsPage {
  private readonly api = inject(StationsApi);
  private readonly zonesApi = inject(ZonesApi);
  private readonly session = inject(Session);
  private readonly live = inject(LiveEvents);

  protected readonly stationStates = STATION_STATES;
  protected readonly variables = VARIABLES;
  protected readonly variableLabel = variableLabel;
  protected readonly t = t;
  protected readonly units = UNITS;
  protected readonly positions = POSITIONS;
  protected readonly positionLabel = positionLabel;

  protected readonly stations = signal<Station[]>([]);
  protected readonly zones = signal<Zone[]>([]);
  protected readonly loaded = signal(false);
  protected readonly loadFailed = signal(false);
  protected readonly listStatus = computed(() =>
    loadStatus(this.loaded(), this.loadFailed(), this.stations().length),
  );
  protected readonly includeInactive = signal(false);
  protected readonly editing = signal<Editing | null>(null);
  protected readonly assignments = signal<Record<string, ZonePosition | ''>>({});
  protected readonly pending = signal<LonLat | null>(null);
  protected readonly problem = signal<string | null>(null);
  protected readonly saving = signal(false);
  protected readonly status = signal('');
  protected readonly issued = signal<{ code: string; key: string } | null>(null);
  protected readonly copied = signal(false);
  /** View clock for the relative ages ("hace N s"). */
  protected readonly now = clock(1_000);
  /** Last successful REST load: while the channel is down, silence is judged up to here. */
  private readonly syncedAt = signal(Date.now());
  private readonly asOf = computed(() =>
    dataTime(this.live.status(), this.now(), this.syncedAt(), this.live.lostAt()),
  );
  /** switchMap: only the latest list counts, even if an older request answers later. */
  private readonly stationLoads = new Subject<void>();

  protected readonly canManage = computed(
    () => this.session.me()?.permissions.includes('territory:manage') ?? false,
  );
  protected readonly zoneNames = computed(
    () => new Map(this.zones().map((zone) => [zone.id, zone.name])),
  );
  /** "7 estaciones · 6 reportando · 1 sin reportar · 1 sin zona", readable at a glance. */
  protected readonly subtitle = computed(() => {
    if (!this.loaded()) return '';
    const active = this.stations().filter((station) => station.status === 'active');
    const states = active.map((station) => stationState(station, this.asOf()));
    const parts = [t('stations.count', { count: active.length })];
    parts.push(t('stations.reporting', { count: states.filter((s) => s === 'reporting').length }));
    const silent = states.filter((s) => s === 'silent').length;
    if (silent > 0) parts.push(t('stations.silent', { count: silent }));
    const unzoned = active.filter((station) => !station.has_zone).length;
    if (unzoned > 0) parts.push(t('stations.unzoned', { count: unzoned }));
    return parts.join(' · ');
  });

  protected readonly form = new FormGroup({
    code: new FormControl('', { nonNullable: true }),
    name: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(120)],
    }),
    variable: new FormControl<Variable>('discharge', { nonNullable: true }),
    source: new FormControl<Source>('sensor', { nonNullable: true }),
    expected_interval_s: new FormControl(10, {
      nonNullable: true,
      validators: [Validators.required, Validators.min(5), Validators.max(86400)],
    }),
    silence_multiplier: new FormControl(3, {
      nonNullable: true,
      validators: [Validators.required, Validators.min(1), Validators.max(20)],
    }),
    lon: new FormControl<number | null>(null, [Validators.min(-180), Validators.max(180)]),
    lat: new FormControl<number | null>(null, [Validators.min(-90), Validators.max(90)]),
  });

  constructor() {
    this.stationLoads
      .pipe(
        switchMap(() =>
          this.api.list(this.includeInactive()).pipe(
            catchError(() => {
              this.loadFailed.set(true);
              return EMPTY;
            }),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((stations) => {
        this.stations.set(keepNewerHeartbeats(stations, this.stations()));
        this.syncedAt.set(Date.now());
        this.loaded.set(true);
        this.loadFailed.set(false);
      });
    this.load();

    // Heartbeats arrive as live events. If the channel drops, LiveEvents asks for a reload
    // every 15 s instead, and silence is judged against `asOf`, not the clock.
    this.live.reload$.pipe(takeUntilDestroyed()).subscribe(() => this.load());
    this.live.heartbeats$
      .pipe(takeUntilDestroyed())
      .subscribe(({ stationId, heartbeat }) =>
        this.stations.update((stations) => withHeartbeat(stations, stationId, heartbeat)),
      );
  }

  protected load(): void {
    this.stationLoads.next();
    this.zonesApi.list().subscribe({ next: (zones) => this.zones.set(zones) });
  }

  protected toggleInactive(checked: boolean): void {
    this.includeInactive.set(checked);
    this.load();
  }

  protected stateOf(station: Station) {
    return stationState(station, this.asOf());
  }

  protected age(iso: string): string {
    return ageText(iso, this.now());
  }

  /** Exact time in the organization's time zone, for the `title` of the age. */
  protected time(iso: string): string {
    const timezone = this.session.me()?.organization_timezone ?? 'UTC';
    return localTime(iso, timezone);
  }

  protected number(value: number): string {
    return measurement(value);
  }

  protected zoneSummary(station: Station): string {
    return station.zones
      .map((z) => {
        const zone = this.zoneNames().get(z.zone_id) ?? t('stations.aZone');
        return `${zone} (${positionLabel(z.position).toLowerCase()})`;
      })
      .join(', ');
  }

  protected startCreate(): void {
    this.form.reset();
    this.form.controls.code.addValidators([Validators.required]);
    this.form.controls.code.updateValueAndValidity();
    this.assignments.set({});
    this.pending.set(null);
    this.problem.set(null);
    this.editing.set({ kind: 'new' });
    this.status.set(t('stations.pickHint'));
  }

  protected startEdit(station: Station): void {
    const [lon, lat] = station.location.coordinates;
    this.form.controls.code.clearValidators();
    this.form.setValue({
      code: station.code,
      name: station.name,
      variable: station.variable,
      source: station.source,
      expected_interval_s: station.expected_interval_s,
      silence_multiplier: station.silence_multiplier,
      lon,
      lat,
    });
    this.assignments.set(Object.fromEntries(station.zones.map((z) => [z.zone_id, z.position])));
    this.pending.set([lon, lat]);
    this.problem.set(null);
    this.editing.set({ kind: 'edit', station });
    this.status.set(t('stations.editHint', { code: station.code }));
  }

  protected cancel(): void {
    this.editing.set(null);
    this.pending.set(null);
    this.problem.set(null);
    this.status.set('');
  }

  protected onPicked([lon, lat]: LonLat): void {
    const rounded: LonLat = [round6(lon), round6(lat)];
    this.form.patchValue({ lon: rounded[0], lat: rounded[1] });
    this.pending.set(rounded);
  }

  protected onCoordinatesTyped(): void {
    const { lon, lat } = this.form.getRawValue();
    this.pending.set(lon !== null && lat !== null ? [lon, lat] : null);
  }

  protected setPosition(zoneId: string, position: string): void {
    this.assignments.update((current) => ({ ...current, [zoneId]: position as ZonePosition | '' }));
  }

  protected save(): void {
    const editing = this.editing();
    if (!editing) return;
    const value = this.form.getRawValue();
    if (value.lon === null || value.lat === null) {
      this.problem.set(t('stations.missingLocation'));
      return;
    }
    if (this.form.invalid || !value.name.trim()) {
      this.form.markAllAsTouched();
      this.problem.set(t('ui.checkFields'));
      return;
    }
    const body: StationInput = {
      name: value.name.trim(),
      variable: value.variable,
      source: value.source,
      expected_interval_s: value.expected_interval_s,
      silence_multiplier: value.silence_multiplier,
      location: { type: 'Point', coordinates: [value.lon, value.lat] },
      status: editing.kind === 'edit' ? editing.station.status : 'active',
      zones: Object.entries(this.assignments())
        .filter(([, position]) => position !== '')
        .map(([zone_id, position]) => ({ zone_id, position: position as ZonePosition })),
    };
    this.saving.set(true);
    if (editing.kind === 'new') {
      this.api.create(value.code.trim(), body).subscribe({
        next: (issued) => this.done(t('stations.created', { code: issued.station.code }), issued),
        error: (error: unknown) => this.failed(error),
      });
    } else {
      this.api.update(editing.station.id, body).subscribe({
        next: (station) => this.done(t('stations.saved', { code: station.code })),
        error: (error: unknown) => this.failed(error),
      });
    }
  }

  protected rotate(station: Station): void {
    if (!confirm(t('stations.confirmRotate', { code: station.code }))) return;
    this.api.rotateKey(station.id).subscribe({
      next: (issued) => this.done(t('stations.rotated', { code: station.code }), issued),
      error: (error: unknown) => this.status.set(stationProblem(error)),
    });
  }

  protected deactivate(station: Station): void {
    if (!confirm(t('stations.confirmDeactivate', { code: station.code }))) return;
    this.api.deactivate(station.id).subscribe({
      next: () => this.done(t('stations.deactivated', { code: station.code })),
      error: (error: unknown) => this.status.set(stationProblem(error)),
    });
  }

  protected reactivate(station: Station): void {
    const { name, variable, source, expected_interval_s, silence_multiplier, location, zones } =
      station;
    const body: StationInput = {
      name,
      variable,
      source,
      expected_interval_s,
      silence_multiplier,
      location,
      zones,
      status: 'active',
    };
    this.api.update(station.id, body).subscribe({
      next: () => this.done(t('stations.reactivated', { code: station.code })),
      error: (error: unknown) => this.status.set(stationProblem(error)),
    });
  }

  protected async copyKey(): Promise<void> {
    const issued = this.issued();
    if (!issued) return;
    await navigator.clipboard.writeText(issued.key);
    this.copied.set(true);
  }

  protected dismissKey(): void {
    this.issued.set(null);
    this.copied.set(false);
  }

  private done(message: string, issued?: IssuedKey): void {
    this.saving.set(false);
    this.cancel();
    this.status.set(message);
    if (issued) {
      this.issued.set({ code: issued.station.code, key: issued.api_key });
      this.copied.set(false);
    }
    this.load();
  }

  private failed(error: unknown): void {
    this.saving.set(false);
    this.problem.set(stationProblem(error));
  }
}

function round6(value: number): number {
  // 6 decimals ≈ 0.1 m: more precision than a map click is pointless.
  return Math.round(value * 1e6) / 1e6;
}
