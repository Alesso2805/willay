import { Component, computed, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Session } from '../session';
import { LoadState, loadStatus } from '../ui/load-state';
import { Notice } from '../ui/notice';
import { StateBadge } from '../ui/state-badge';
import { RISK_LEVEL_STATES } from '../ui/visual-states';
import { DrawnGeometry, MapMode, ZoneMap } from './zone-map';
import { RISK_LABELS, RISK_LEVELS, SaveProblem, saveProblem } from './zone-presentation';
import { RiskLevel, Zone, ZoneInput, ZonesApi } from './zones.api';

type Editing = { kind: 'new' } | { kind: 'edit'; zone: Zone };

@Component({
  selector: 'app-zones-page',
  imports: [ZoneMap, ReactiveFormsModule, LoadState, Notice, StateBadge],
  templateUrl: './zones-page.html',
})
export class ZonesPage {
  private readonly api = inject(ZonesApi);
  private readonly session = inject(Session);

  protected readonly riskLevels = RISK_LEVELS;
  protected readonly riskLabels = RISK_LABELS;
  protected readonly riskStates = RISK_LEVEL_STATES;

  protected readonly zones = signal<Zone[]>([]);
  protected readonly loaded = signal(false);
  protected readonly loadFailed = signal(false);
  protected readonly listStatus = computed(() =>
    loadStatus(this.loaded(), this.loadFailed(), this.zones().length),
  );
  protected readonly includeInactive = signal(false);
  protected readonly editing = signal<Editing | null>(null);
  protected readonly geometry = signal<DrawnGeometry | null>(null);
  protected readonly problem = signal<SaveProblem | null>(null);
  protected readonly saving = signal(false);
  protected readonly status = signal('');

  /** Solo oculta acciones: la API valida el permiso en cada petición. */
  protected readonly canManage = computed(
    () => this.session.me()?.permissions.includes('territory:manage') ?? false,
  );
  protected readonly mapMode = computed<MapMode>(() => {
    const editing = this.editing();
    if (editing?.kind === 'new') return { kind: 'draw' };
    if (editing?.kind === 'edit') return { kind: 'edit', zoneId: editing.zone.id };
    return { kind: 'view' };
  });
  protected readonly vertexCount = computed(() => {
    const geometry = this.geometry();
    if (!geometry) return 0;
    const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
    // Cada anillo repite el primer punto al final para cerrarse.
    return polygons.flat().reduce((total, ring) => total + ring.length - 1, 0);
  });

  protected readonly form = new FormGroup({
    name: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(120)],
    }),
    risk_level: new FormControl<RiskLevel>('high', { nonNullable: true }),
    population_estimate: new FormControl<number | null>(null, [Validators.min(0)]),
    description: new FormControl('', { nonNullable: true, validators: [Validators.maxLength(2000)] }),
  });

  constructor() {
    this.load();
  }

  protected load(): void {
    this.api.list(this.includeInactive()).subscribe({
      next: (zones) => {
        this.zones.set(zones);
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

  protected startCreate(): void {
    this.form.reset();
    this.geometry.set(null);
    this.problem.set(null);
    this.editing.set({ kind: 'new' });
    this.status.set('Dibuja el polígono en el mapa: un clic por vértice y cierra en el primero.');
  }

  protected startEdit(zone: Zone): void {
    this.form.setValue({
      name: zone.name,
      risk_level: zone.risk_level,
      population_estimate: zone.population_estimate,
      description: zone.description ?? '',
    });
    this.geometry.set(zone.geometry);
    this.problem.set(null);
    this.editing.set({ kind: 'edit', zone });
    this.status.set(`Editando ${zone.name}. Arrastra los vértices en el mapa para cambiar la forma.`);
  }

  protected cancel(): void {
    this.editing.set(null);
    this.geometry.set(null);
    this.problem.set(null);
    this.status.set('');
  }

  protected onGeometry(geometry: DrawnGeometry): void {
    this.geometry.set(geometry);
    this.problem.set(null);
  }

  protected save(): void {
    const editing = this.editing();
    const geometry = this.geometry();
    const name = this.form.controls.name.value.trim();
    if (!editing) return;
    if (!geometry) {
      this.problem.set({ message: 'Falta dibujar el polígono en el mapa.', point: null });
      return;
    }
    if (this.form.invalid || !name) {
      this.form.markAllAsTouched();
      this.problem.set({ message: 'Revisa los campos marcados.', point: null });
      return;
    }
    const value = this.form.getRawValue();
    const body: ZoneInput = {
      name,
      description: value.description.trim() || null,
      risk_level: value.risk_level,
      population_estimate: value.population_estimate,
      geometry,
      is_active: editing.kind === 'edit' ? editing.zone.is_active : true,
    };
    const request =
      editing.kind === 'new' ? this.api.create(body) : this.api.update(editing.zone.id, body);
    this.saving.set(true);
    request.subscribe({
      next: (zone) => {
        this.saving.set(false);
        this.cancel();
        this.status.set(`Zona «${zone.name}» guardada.`);
        this.load();
      },
      error: (error: unknown) => {
        this.saving.set(false);
        this.problem.set(saveProblem(error));
      },
    });
  }

  protected reactivate(zone: Zone): void {
    const { name, description, risk_level, population_estimate, geometry } = zone;
    const body: ZoneInput = { name, description, risk_level, population_estimate, geometry, is_active: true };
    this.api.update(zone.id, body).subscribe({
      next: () => {
        this.status.set(`Zona «${zone.name}» reactivada.`);
        this.load();
      },
      error: (error: unknown) => this.status.set(saveProblem(error).message),
    });
  }

  protected deactivate(zone: Zone): void {
    if (!confirm(`¿Desactivar la zona «${zone.name}»? Sus reglas dejarán de aplicarse.`)) return;
    this.api.deactivate(zone.id).subscribe({
      next: () => {
        this.status.set(`Zona «${zone.name}» desactivada.`);
        this.load();
      },
      error: (error: unknown) => this.status.set(saveProblem(error).message),
    });
  }
}
