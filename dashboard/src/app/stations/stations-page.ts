import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Session } from '../session';
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
  POSITION_LABELS,
  UNITS,
  VARIABLE_LABELS,
  VARIABLES,
  stationProblem,
  stationState,
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

  protected readonly stationStates = STATION_STATES;
  protected readonly variables = VARIABLES;
  protected readonly variableLabels = VARIABLE_LABELS;
  protected readonly units = UNITS;
  protected readonly positions = Object.keys(POSITION_LABELS) as ZonePosition[];
  protected readonly positionLabels = POSITION_LABELS;

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
  /** View clock for the relative ages ("hace N s"); refreshed every 15 s. */
  protected readonly now = signal(Date.now());

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
    const states = active.map((station) => stationState(station, this.now()));
    const parts = [`${active.length} ${active.length === 1 ? 'estación' : 'estaciones'}`];
    parts.push(`${states.filter((s) => s === 'reporting').length} reportando`);
    const silent = states.filter((s) => s === 'silent').length;
    if (silent > 0) parts.push(`${silent} sin reportar`);
    const unzoned = active.filter((station) => !station.has_zone).length;
    if (unzoned > 0) parts.push(`${unzoned} sin zona`);
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
    this.load();
    // The clock and the heartbeats advance together: if only the clock advanced, a station
    // that keeps reporting would show "Sin reportar" K × interval after opening the page.
    // VIG-25 replaces this polling with SSE events.
    const timer = setInterval(() => {
      this.now.set(Date.now());
      this.loadStations();
    }, 15_000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  protected load(): void {
    this.loadStations();
    this.zonesApi.list().subscribe({ next: (zones) => this.zones.set(zones) });
  }

  private loadStations(): void {
    this.api.list(this.includeInactive()).subscribe({
      next: (stations) => {
        this.stations.set(stations);
        this.loaded.set(true);
        this.loadFailed.set(false);
      },
      error: () => this.loadFailed.set(true),
    });
  }

  protected toggleInactive(checked: boolean): void {
    this.includeInactive.set(checked);
    this.load();
  }

  protected stateOf(station: Station) {
    return stationState(station, this.now());
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
      .map((z) => `${this.zoneNames().get(z.zone_id) ?? 'zona'} (${POSITION_LABELS[z.position].toLowerCase()})`)
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
    this.status.set('Haz clic en el mapa para ubicar la estación, o escribe longitud y latitud.');
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
    this.status.set(`Editando ${station.code}. Haz clic en el mapa para moverla.`);
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
      this.problem.set('Falta la ubicación: haz clic en el mapa o escribe longitud y latitud.');
      return;
    }
    if (this.form.invalid || !value.name.trim()) {
      this.form.markAllAsTouched();
      this.problem.set('Revisa los campos marcados.');
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
        next: (issued) => this.done(`Estación ${issued.station.code} creada.`, issued),
        error: (error: unknown) => this.failed(error),
      });
    } else {
      this.api.update(editing.station.id, body).subscribe({
        next: (station) => this.done(`Estación ${station.code} guardada.`),
        error: (error: unknown) => this.failed(error),
      });
    }
  }

  protected rotate(station: Station): void {
    const question = `¿Rotar la clave de ${station.code}? La actual deja de funcionar al instante y la estación recibirá 401 hasta que la reconfigures.`;
    if (!confirm(question)) return;
    this.api.rotateKey(station.id).subscribe({
      next: (issued) => this.done(`Clave de ${station.code} rotada.`, issued),
      error: (error: unknown) => this.status.set(stationProblem(error)),
    });
  }

  protected deactivate(station: Station): void {
    if (!confirm(`¿Desactivar ${station.code}? Sus lotes recibirán 403.`)) return;
    this.api.deactivate(station.id).subscribe({
      next: () => this.done(`Estación ${station.code} desactivada.`),
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
      next: () => this.done(`Estación ${station.code} reactivada.`),
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
