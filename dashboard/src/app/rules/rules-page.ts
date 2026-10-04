import { Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { map, startWith } from 'rxjs';
import { t } from '../i18n/i18n';
import { causeLabel } from '../incidents/incident-presentation';
import { ReadingsChart } from '../incidents/readings-chart';
import { IncidentReadings } from '../incidents/incidents.api';
import { Session } from '../session';
import { Station, StationsApi } from '../stations/stations.api';
import { Icon } from '../ui/icon';
import { LoadState, loadStatus } from '../ui/load-state';
import { Notice } from '../ui/notice';
import { PageHeader } from '../ui/page-header';
import { StateBadge } from '../ui/state-badge';
import { RULE_STATES, SEVERITIES, Severity } from '../ui/visual-states';
import { Zone, ZonesApi } from '../zones/zones.api';
import {
  OPERATORS,
  cooldownText,
  fieldErrors,
  previewSummary,
  ruleProblem,
  ruleSummary,
  silenceText,
  operatorLabel,
} from './rule-presentation';
import {
  Direction,
  Ref,
  Rule,
  RuleInput,
  RuleParams,
  RulePreview,
  RuleType,
  RulesApi,
  ThresholdOperator,
  ThresholdParams,
} from './rules.api';

type Editing = { kind: 'new' } | { kind: 'edit'; rule: Rule };

const RULE_TYPES: RuleType[] = ['threshold', 'rate_of_change', 'silence'];
const SEVERITY_ORDER: Severity[] = ['info', 'warning', 'critical'];
const MAX_COOLDOWN_MIN = 1440;

/**
 * VIG-27: the rules that open incidents. Everyone sees them; operator and admin create, edit
 * and deactivate them, and preview a draft over the last 24 h before saving it.
 */
@Component({
  selector: 'app-rules-page',
  imports: [ReactiveFormsModule, LoadState, Notice, StateBadge, PageHeader, Icon, ReadingsChart],
  templateUrl: './rules-page.html',
})
export class RulesPage {
  private readonly api = inject(RulesApi);
  private readonly stationsApi = inject(StationsApi);
  private readonly zonesApi = inject(ZonesApi);
  private readonly session = inject(Session);

  protected readonly ruleTypes = RULE_TYPES;
  protected readonly typeLabel = causeLabel;
  protected readonly severities = SEVERITIES;
  protected readonly t = t;
  protected readonly severityOrder = SEVERITY_ORDER;
  protected readonly ruleStates = RULE_STATES;
  protected readonly operatorLabel = operatorLabel;
  protected readonly operators = OPERATORS;
  protected readonly cooldown = cooldownText;

  protected readonly rules = signal<Rule[]>([]);
  protected readonly zones = signal<Zone[]>([]);
  protected readonly stations = signal<Station[]>([]);
  protected readonly policies = signal<Ref[]>([]);
  protected readonly loaded = signal(false);
  protected readonly loadFailed = signal(false);
  protected readonly listStatus = computed(() =>
    loadStatus(this.loaded(), this.loadFailed(), this.rules().length),
  );
  protected readonly includeInactive = signal(false);
  protected readonly editing = signal<Editing | null>(null);
  protected readonly errors = signal<Record<string, string>>({});
  protected readonly problem = signal<string | null>(null);
  protected readonly saving = signal(false);
  protected readonly status = signal('');
  protected readonly preview = signal<RulePreview | null>(null);
  protected readonly previewing = signal(false);

  protected readonly canManage = computed(
    () => this.session.me()?.permissions.includes('rules:manage') ?? false,
  );
  protected readonly timezone = computed(() => this.session.me()?.organization_timezone ?? 'UTC');
  private readonly stationById = computed(() => new Map(this.stations().map((s) => [s.id, s])));

  /** Rules by zone, in the API's order (zone, type, station). */
  protected readonly byZone = computed(() => {
    const groups = new Map<string, { zone: Ref; rules: Rule[] }>();
    for (const rule of this.rules()) {
      const group = groups.get(rule.zone.id) ?? { zone: rule.zone, rules: [] };
      group.rules.push(rule);
      groups.set(rule.zone.id, group);
    }
    return [...groups.values()];
  });
  protected readonly subtitle = computed(() => {
    if (!this.loaded()) return '';
    const active = this.rules().filter((r) => r.is_active).length;
    const zones = new Set(this.rules().map((r) => r.zone.id)).size;
    return `${t('rules.active', { count: active })} ${t('rules.inZones', { count: zones })}`;
  });

  protected readonly form = new FormGroup({
    type: new FormControl<RuleType>('threshold', { nonNullable: true }),
    zone_id: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    station_id: new FormControl('', { nonNullable: true }),
    operator: new FormControl<ThresholdOperator>('gt', { nonNullable: true }),
    value: new FormControl<number | null>(null),
    consecutive: new FormControl<number | null>(2, { nonNullable: true }),
    direction: new FormControl<Direction>('down', { nonNullable: true }),
    delta: new FormControl<number | null>(null),
    window_minutes: new FormControl<number | null>(10, { nonNullable: true }),
    severity: new FormControl<Severity>('warning', { nonNullable: true }),
    escalation_policy_id: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    cooldown_min: new FormControl<number | null>(30, { nonNullable: true }),
  });
  // getRawValue: valueChanges leaves out disabled controls, and the type is disabled when editing.
  private readonly draft = toSignal(
    this.form.valueChanges.pipe(
      map(() => this.form.getRawValue()),
      startWith(this.form.getRawValue()),
    ),
    { initialValue: this.form.getRawValue() },
  );
  protected readonly draftType = computed(() => this.draft().type);
  /** The zone's active stations: a rule on any other would never fire. */
  protected readonly zoneStations = computed(() => {
    const zoneId = this.draft().zone_id;
    return this.stations().filter(
      (s) => s.status === 'active' && s.zones.some((z) => z.zone_id === zoneId),
    );
  });
  protected readonly draftStation = computed(() => this.stationById().get(this.draft().station_id));
  /** Active zones, plus the edited rule's own if it was deactivated since. */
  protected readonly zoneOptions = computed((): Ref[] => {
    const zones: Ref[] = this.zones().map(({ id, name }) => ({ id, name }));
    const editing = this.editing();
    const own = editing?.kind === 'edit' ? editing.rule.zone : null;
    return own && !zones.some((z) => z.id === own.id) ? [...zones, own] : zones;
  });

  constructor() {
    this.load();
    this.zonesApi.list().subscribe({ next: (zones) => this.zones.set(zones) });
    // Every station, inactive ones too: a rule may still point to one.
    this.stationsApi.list(true).subscribe({ next: (stations) => this.stations.set(stations) });
    if (this.canManage()) {
      this.api.policies().subscribe({ next: (policies) => this.policies.set(policies) });
    }
    // A preview answers for the draft it was asked for: any change makes it stale.
    this.form.valueChanges.subscribe(() => this.preview.set(null));
    // A different zone has different stations: the chosen one may no longer apply.
    this.form.controls.zone_id.valueChanges.subscribe(() => {
      if (!this.zoneStations().some((s) => s.id === this.form.controls.station_id.value)) {
        this.form.controls.station_id.setValue('');
      }
    });
  }

  protected load(): void {
    this.api.list(this.includeInactive()).subscribe({
      next: (rules) => {
        this.rules.set(rules);
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

  protected summary(rule: Rule): string {
    return ruleSummary(rule, rule.station ? this.stationById().get(rule.station.id) : undefined);
  }

  protected silenceOf(station: Station): string {
    return silenceText(station);
  }

  protected error(field: string): string | null {
    return this.errors()[field] ?? null;
  }

  protected startCreate(): void {
    this.form.reset();
    this.form.controls.type.enable();
    this.form.patchValue({ escalation_policy_id: this.policies()[0]?.id ?? '' });
    this.clearFeedback();
    this.editing.set({ kind: 'new' });
  }

  protected startEdit(rule: Rule): void {
    this.form.reset();
    const p = rule.params as Partial<ThresholdParams> &
      Partial<{ direction: Direction; delta: number; window_minutes: number }>;
    this.form.patchValue({
      type: rule.type,
      zone_id: rule.zone.id,
      station_id: rule.station?.id ?? '',
      severity: rule.severity,
      escalation_policy_id: rule.escalation_policy.id,
      cooldown_min: rule.cooldown_s / 60,
      ...(rule.type === 'threshold'
        ? { operator: p.operator, value: p.value, consecutive: p.consecutive }
        : {}),
      ...(rule.type === 'rate_of_change'
        ? { direction: p.direction, delta: p.delta, window_minutes: p.window_minutes }
        : {}),
    });
    // The type never changes: to watch something else, deactivate it and create another.
    this.form.controls.type.disable();
    this.clearFeedback();
    this.editing.set({ kind: 'edit', rule });
  }

  protected cancel(): void {
    this.editing.set(null);
    this.clearFeedback();
  }

  protected showPreview(): void {
    const body = this.body();
    if (!body) return;
    this.previewing.set(true);
    this.api
      .preview({
        type: body.type,
        zone_id: body.zone_id,
        station_id: body.station_id,
        params: body.params,
      })
      .subscribe({
        next: (preview) => {
          this.previewing.set(false);
          this.preview.set(preview);
        },
        error: (error: unknown) => this.failed(error, () => this.previewing.set(false)),
      });
  }

  protected save(): void {
    const editing = this.editing();
    const body = this.body();
    if (!editing || !body) return;
    this.saving.set(true);
    const request =
      editing.kind === 'new' ? this.api.create(body) : this.api.update(editing.rule.id, body);
    request.subscribe({
      next: (rule) => {
        this.saving.set(false);
        this.cancel();
        const where = rule.station?.code ?? rule.zone.name;
        this.done(t(editing.kind === 'new' ? 'rules.created' : 'rules.saved', { where }));
      },
      error: (error: unknown) => this.failed(error, () => this.saving.set(false)),
    });
  }

  protected deactivate(rule: Rule): void {
    const where = rule.station?.code ?? rule.zone.name;
    if (!confirm(t('rules.confirmDeactivate', { cause: causeLabel(rule.type), where }))) return;
    this.api.deactivate(rule.id).subscribe({
      next: () => this.done(t('rules.deactivated', { where })),
      error: (error: unknown) => this.status.set(ruleProblem(error)),
    });
  }

  protected reactivate(rule: Rule): void {
    const where = rule.station?.code ?? rule.zone.name;
    const body: RuleInput = {
      type: rule.type,
      zone_id: rule.zone.id,
      station_id: rule.station?.id ?? null,
      params: rule.params,
      severity: rule.severity,
      escalation_policy_id: rule.escalation_policy.id,
      cooldown_s: rule.cooldown_s,
      is_active: true,
    };
    this.api.update(rule.id, body).subscribe({
      next: () => this.done(t('rules.reactivated', { where })),
      error: (error: unknown) => this.status.set(ruleProblem(error)),
    });
  }

  /** The draft as the API expects it, or null after marking what is missing. */
  private body(): RuleInput | null {
    const v = this.form.getRawValue();
    const errors: Record<string, string> = {};
    if (!v.zone_id) errors['zone_id'] = t('rules.zoneRequired');
    if (v.type !== 'silence' && !v.station_id) errors['station_id'] = t('rules.stationRequired');
    let params: RuleParams = {};
    if (v.type === 'threshold') {
      if (v.value === null || !Number.isFinite(v.value))
        errors['value'] = t('rules.valueRequired');
      if (!isWhole(v.consecutive, 1, 60)) errors['consecutive'] = t('rules.consecutiveRange');
      params = { operator: v.operator, value: v.value ?? 0, consecutive: v.consecutive ?? 1 };
    } else if (v.type === 'rate_of_change') {
      if (v.delta === null || !(v.delta > 0)) errors['delta'] = t('rules.deltaPositive');
      if (!isWhole(v.window_minutes, 1, 60)) errors['window_minutes'] = t('rules.windowRange');
      params = {
        direction: v.direction,
        delta: v.delta ?? 0,
        window_minutes: v.window_minutes ?? 1,
      };
    }
    if (!v.escalation_policy_id)
      errors['escalation_policy_id'] = t('rules.policyRequired');
    if (v.cooldown_min === null || !(v.cooldown_min >= 0 && v.cooldown_min <= MAX_COOLDOWN_MIN)) {
      errors['cooldown_min'] = t('rules.cooldownRange', { max: MAX_COOLDOWN_MIN });
    }
    this.errors.set(errors);
    if (Object.keys(errors).length > 0) {
      this.problem.set(t('ui.checkFields'));
      return null;
    }
    this.problem.set(null);
    const editing = this.editing();
    return {
      type: v.type,
      zone_id: v.zone_id,
      station_id: v.station_id || null,
      params,
      severity: v.severity,
      escalation_policy_id: v.escalation_policy_id,
      cooldown_s: Math.round((v.cooldown_min ?? 0) * 60),
      is_active: editing?.kind === 'edit' ? editing.rule.is_active : true,
    };
  }

  /** The preview of one station, shaped for the incident chart. */
  protected chartOf(
    station: RulePreview['stations'][number],
    preview: RulePreview,
  ): IncidentReadings {
    const v = this.form.getRawValue();
    return {
      station_code: station.station.code,
      unit: station.station.unit,
      window_start: preview.since,
      window_end: preview.until,
      source: 'readings',
      readings: station.readings,
      threshold:
        v.type === 'threshold' && v.value !== null
          ? { operator: v.operator, value: v.value }
          : null,
    };
  }

  protected marksOf(station: RulePreview['stations'][number]) {
    return station.firings.map((firing) => ({ at: firing.at, label: t('rules.previewMark') }));
  }

  protected previewText(station: RulePreview['stations'][number]): string {
    return previewSummary(station, this.draftType() === 'silence');
  }

  private failed(error: unknown, stop: () => void): void {
    stop();
    const errors = fieldErrors(error);
    if (errors['cooldown_s']) errors['cooldown_min'] = errors['cooldown_s'];
    this.errors.set(errors);
    this.problem.set(ruleProblem(error));
  }

  private clearFeedback(): void {
    this.errors.set({});
    this.problem.set(null);
    this.preview.set(null);
  }

  private done(message: string): void {
    this.status.set(message);
    this.load();
  }
}

function isWhole(value: number | null, min: number, max: number): boolean {
  return value !== null && Number.isInteger(value) && value >= min && value <= max;
}
