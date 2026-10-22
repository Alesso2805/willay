import { Component, computed, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { t } from '../i18n/i18n';
import { Session } from '../session';
import { Icon } from '../ui/icon';
import { LoadState, loadStatus } from '../ui/load-state';
import { Notice } from '../ui/notice';
import { PageHeader } from '../ui/page-header';
import { StateBadge } from '../ui/state-badge';
import { GROUP_STATES, GroupState } from '../ui/visual-states';
import { Zone, ZonesApi } from '../zones/zones.api';
import { channelStates, contactProblem } from './contact-presentation';
import { ContactTabs } from './contact-tabs';
import { Contact, ContactsApi } from './contacts.api';
import { ContactGroup, GroupsApi, Ref } from './groups.api';

type Editing = { kind: 'new' } | { kind: 'edit'; group: ContactGroup };

/** A group reaches nobody without members, and nobody is alerted through it without a policy. */
export function groupStates(group: ContactGroup): GroupState[] {
  const states: GroupState[] = [];
  if (group.members.length === 0) states.push('empty');
  if (group.policies.length === 0) states.push('unused');
  return states;
}

/** Who each escalation level notifies. Admin and operator read; only admin changes. */
@Component({
  selector: 'app-groups-page',
  imports: [ReactiveFormsModule, LoadState, Notice, StateBadge, PageHeader, Icon, ContactTabs],
  templateUrl: './groups-page.html',
})
export class GroupsPage {
  private readonly api = inject(GroupsApi);
  private readonly contactsApi = inject(ContactsApi);
  private readonly zonesApi = inject(ZonesApi);
  private readonly session = inject(Session);
  protected readonly t = t;

  protected readonly groupLabels = GROUP_STATES;
  protected readonly groups = signal<ContactGroup[]>([]);
  protected readonly contacts = signal<Contact[]>([]);
  protected readonly zones = signal<Zone[]>([]);
  protected readonly loaded = signal(false);
  protected readonly loadFailed = signal(false);
  protected readonly listStatus = computed(() =>
    loadStatus(this.loaded(), this.loadFailed(), this.groups().length),
  );
  protected readonly editing = signal<Editing | null>(null);
  protected readonly members = signal<ReadonlySet<string>>(new Set());
  protected readonly problem = signal<string | null>(null);
  protected readonly saving = signal(false);
  protected readonly status = signal('');

  protected readonly canView = computed(
    () => this.session.me()?.permissions.includes('contacts:view_details') ?? false,
  );
  protected readonly canManage = computed(
    () => this.session.me()?.permissions.includes('contacts:manage') ?? false,
  );
  /** "3 grupos · 1 sin miembros · 1 sin política". */
  protected readonly subtitle = computed(() => {
    if (!this.loaded()) return '';
    const groups = this.groups();
    const parts = [t('groups.count', { count: groups.length })];
    const empty = groups.filter((g) => g.members.length === 0).length;
    if (empty > 0) parts.push(t('groups.emptyCount', { count: empty }));
    const unused = groups.filter((g) => g.policies.length === 0).length;
    if (unused > 0) parts.push(t('groups.unusedCount', { count: unused }));
    return parts.join(' · ');
  });
  /** Active zones, plus the edited group's own if it was deactivated since. */
  protected readonly zoneOptions = computed((): Ref[] => {
    const zones: Ref[] = this.zones().map(({ id, name }) => ({ id, name }));
    const editing = this.editing();
    const current = editing?.kind === 'edit' ? editing.group.zone : null;
    return current && !zones.some((z) => z.id === current.id) ? [...zones, current] : zones;
  });

  protected readonly form = new FormGroup({
    name: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(120)],
    }),
    zone_id: new FormControl('', { nonNullable: true }),
  });

  constructor() {
    if (!this.canView()) return;
    this.load();
    if (this.canManage()) {
      // Only the form needs them: who can be a member, and which zone it covers.
      this.contactsApi.list().subscribe({ next: (contacts) => this.contacts.set(contacts) });
      this.zonesApi.list().subscribe({ next: (zones) => this.zones.set(zones) });
    }
  }

  protected load(): void {
    this.api.list().subscribe({
      next: (groups) => {
        this.groups.set(groups);
        this.loaded.set(true);
        this.loadFailed.set(false);
      },
      error: () => this.loadFailed.set(true),
    });
  }

  protected states(group: ContactGroup): GroupState[] {
    return groupStates(group);
  }

  protected names(refs: Ref[]): string {
    return refs.map((ref) => ref.name).join(', ');
  }

  /** Flags a contact no alert reaches, so the admin does not count on them. */
  protected unreachable(contact: Contact): boolean {
    return channelStates(contact).includes('none');
  }

  protected startCreate(): void {
    this.form.reset();
    this.members.set(new Set());
    this.problem.set(null);
    this.editing.set({ kind: 'new' });
  }

  protected startEdit(group: ContactGroup): void {
    this.form.setValue({ name: group.name, zone_id: group.zone?.id ?? '' });
    this.members.set(new Set(group.members.map((m) => m.id)));
    this.problem.set(null);
    this.editing.set({ kind: 'edit', group });
  }

  protected cancel(): void {
    this.editing.set(null);
    this.problem.set(null);
  }

  protected toggleMember(id: string, checked: boolean): void {
    this.members.update((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  protected save(): void {
    const editing = this.editing();
    if (!editing) return;
    const value = this.form.getRawValue();
    if (this.form.invalid || !value.name.trim()) {
      this.form.markAllAsTouched();
      this.problem.set(t('groups.nameRequired'));
      return;
    }
    const body = {
      name: value.name.trim(),
      zone_id: value.zone_id || null,
      member_ids: [...this.members()],
    };
    this.saving.set(true);
    const request =
      editing.kind === 'new' ? this.api.create(body) : this.api.update(editing.group.id, body);
    request.subscribe({
      next: (group) => {
        this.saving.set(false);
        this.cancel();
        this.done(t(editing.kind === 'new' ? 'groups.created' : 'groups.saved', { name: group.name }));
      },
      error: (error: unknown) => {
        this.saving.set(false);
        this.problem.set(contactProblem(error, 'group'));
      },
    });
  }

  protected remove(group: ContactGroup): void {
    if (!confirm(t('groups.confirmDelete', { name: group.name }))) return;
    this.api.delete(group.id).subscribe({
      next: () => this.done(t('groups.deleted', { name: group.name })),
      // A 409 means a policy started using it meanwhile: say which and show it as it is now.
      error: (error: unknown) => {
        this.status.set(contactProblem(error, 'group'));
        this.load();
      },
    });
  }

  private done(message: string): void {
    this.status.set(message);
    this.load();
  }
}
