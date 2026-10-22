import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { forkJoin } from 'rxjs';
import { t } from '../i18n/i18n';
import { Session } from '../session';
import { Icon } from '../ui/icon';
import { LoadState, loadStatus } from '../ui/load-state';
import { Notice } from '../ui/notice';
import { PageHeader } from '../ui/page-header';
import { ContactTabs } from './contact-tabs';
import { ContactGroup, GroupsApi } from './groups.api';
import { Channel, PoliciesApi, Policy } from './policies.api';
import {
  CHANNELS,
  FormErrors,
  LevelDraft,
  draftsOf,
  formErrors,
  inputOf,
  minutesOf,
  targetKey,
} from './policy-form';

type Editing = { kind: 'new' } | { kind: 'edit'; policy: Policy };

const NO_ERRORS: FormErrors = { perLevel: {} };

/**
 * Escalation policies from the dashboard. Ordered levels, each
 * waiting some minutes before the next one is alerted, and the groups it notifies per channel.
 * Everyone in this section reads them; only an admin changes them, and a change also reaches
 * ongoing incidents, because the escalation worker reads the policy when it escalates.
 */
@Component({
  selector: 'app-policies-page',
  imports: [ContactTabs, PageHeader, LoadState, Notice, Icon],
  templateUrl: './policies-page.html',
})
export class PoliciesPage {
  private readonly api = inject(PoliciesApi);
  private readonly groupsApi = inject(GroupsApi);
  private readonly session = inject(Session);
  protected readonly t = t;
  protected readonly channels = CHANNELS;

  protected readonly policies = signal<Policy[]>([]);
  protected readonly groups = signal<ContactGroup[]>([]);
  protected readonly loaded = signal(false);
  protected readonly loadFailed = signal(false);
  protected readonly listStatus = computed(() =>
    loadStatus(this.loaded(), this.loadFailed(), this.policies().length),
  );
  protected readonly canManage = computed(
    () => this.session.me()?.permissions.includes('policies:manage') ?? false,
  );
  protected readonly subtitle = computed(() =>
    this.loaded() ? t('policies.count', { count: this.policies().length }) : '',
  );

  protected readonly editing = signal<Editing | null>(null);
  protected readonly name = signal('');
  protected readonly levels = signal<LevelDraft[]>([]);
  protected readonly errors = signal<FormErrors>(NO_ERRORS);
  protected readonly problem = signal<string | null>(null);
  protected readonly saving = signal(false);
  protected readonly status = signal('');

  constructor() {
    this.load();
  }

  protected load(): void {
    this.loadFailed.set(false);
    forkJoin([this.api.list(), this.groupsApi.list()]).subscribe({
      next: ([policies, groups]) => {
        this.policies.set(policies);
        this.groups.set(groups);
        this.loaded.set(true);
      },
      error: () => this.loadFailed.set(true),
    });
  }

  protected channelLabel(channel: Channel): string {
    return t(`policies.channels.${channel}`);
  }

  /** "Operadores de turno (correo), Brigada Chosica (Telegram)". */
  protected targetsText(level: Policy['levels'][number]): string {
    return level.targets
      .map((target) => `${target.contact_group_name} (${this.channelLabel(target.channel)})`)
      .join(', ');
  }

  protected waitText(policy: Policy, index: number): string {
    const minutes = minutesOf(policy.levels[index].wait_s);
    const last = index === policy.levels.length - 1;
    return last
      ? t('policies.waitThenExhausted', { minutes })
      : t('policies.waitThenNext', { minutes, next: index + 2 });
  }

  protected startCreate(): void {
    this.open({ kind: 'new' }, '', [{ minutes: '2', targets: new Set() }]);
  }

  protected startEdit(policy: Policy): void {
    this.open({ kind: 'edit', policy }, policy.name, draftsOf(policy));
  }

  protected cancel(): void {
    this.editing.set(null);
  }

  protected setName(name: string): void {
    this.name.set(name);
    this.errors.update((errors) => ({ ...errors, name: undefined }));
  }

  protected setMinutes(index: number, minutes: string): void {
    this.levels.update((levels) => levels.map((l, i) => (i === index ? { ...l, minutes } : l)));
    this.clearLevel(index, 'wait');
  }

  /** A problem goes away as soon as its field is corrected, not at the next save. */
  private clearLevel(index: number, field: 'wait' | 'targets'): void {
    this.errors.update((errors) => ({
      ...errors,
      perLevel: { ...errors.perLevel, [index]: { ...errors.perLevel[index], [field]: undefined } },
    }));
  }

  protected toggle(index: number, groupId: string, channel: Channel, on: boolean): void {
    const key = targetKey(groupId, channel);
    this.levels.update((levels) =>
      levels.map((level, i) => {
        if (i !== index) return level;
        const targets = new Set(level.targets);
        if (on) targets.add(key);
        else targets.delete(key);
        return { ...level, targets };
      }),
    );
    this.clearLevel(index, 'targets');
  }

  protected has(level: LevelDraft, groupId: string, channel: Channel): boolean {
    return level.targets.has(targetKey(groupId, channel));
  }

  protected addLevel(): void {
    this.levels.update((levels) => [...levels, { minutes: '2', targets: new Set() }]);
  }

  protected removeLevel(index: number): void {
    this.levels.update((levels) => levels.filter((_, i) => i !== index));
    this.errors.set(NO_ERRORS); // the positions the problems referred to have moved
  }

  protected move(index: number, by: -1 | 1): void {
    this.levels.update((levels) => {
      const moved = [...levels];
      [moved[index], moved[index + by]] = [moved[index + by], moved[index]];
      return moved;
    });
    this.errors.set(NO_ERRORS);
  }

  protected save(event: Event): void {
    event.preventDefault();
    const editing = this.editing();
    if (!editing || this.saving()) return;
    const input = inputOf(this.name(), this.levels());
    this.saving.set(true);
    this.errors.set(NO_ERRORS);
    this.problem.set(null);
    const request =
      editing.kind === 'new' ? this.api.create(input) : this.api.update(editing.policy.id, input);
    request.subscribe({
      next: (policy) => {
        this.saving.set(false);
        this.editing.set(null);
        const key = editing.kind === 'new' ? 'policies.created' : 'policies.updated';
        this.status.set(t(key, { name: policy.name }));
        this.load();
      },
      error: (error: unknown) => {
        this.saving.set(false);
        const errors = formErrors(error);
        if (errors) this.errors.set(errors);
        else this.problem.set(this.problemText(error));
      },
    });
  }

  protected remove(policy: Policy): void {
    if (!confirm(t('policies.confirmDelete', { name: policy.name }))) return;
    this.problem.set(null);
    this.api.delete(policy.id).subscribe({
      next: () => {
        this.status.set(t('policies.deleted', { name: policy.name }));
        this.load();
      },
      error: (error: unknown) => {
        this.problem.set(this.problemText(error));
        this.load();
      },
    });
  }

  private open(editing: Editing, name: string, levels: LevelDraft[]): void {
    this.editing.set(editing);
    this.name.set(name);
    this.levels.set(levels);
    this.errors.set(NO_ERRORS);
    this.problem.set(null);
    this.status.set('');
  }

  /** The API explains a 409 (a rule uses the policy); the rest in our words. */
  private problemText(error: unknown): string {
    if (!(error instanceof HttpErrorResponse)) return t('ui.genericProblem');
    const detail = error.error?.detail;
    if (error.status === 409 && typeof detail === 'string') return detail;
    if (error.status === 403) return t('policies.forbidden');
    if (error.status === 404) return t('policies.gone');
    return t('ui.genericProblem');
  }
}
