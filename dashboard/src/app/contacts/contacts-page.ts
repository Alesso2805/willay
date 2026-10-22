import { Component, computed, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { LANGUAGES, LANGUAGE_NAMES, Language, t } from '../i18n/i18n';
import { Session } from '../session';
import { localTime } from '../ui/formats';
import { Icon } from '../ui/icon';
import { LoadState, loadStatus } from '../ui/load-state';
import { Notice } from '../ui/notice';
import { PageHeader } from '../ui/page-header';
import { StateBadge } from '../ui/state-badge';
import { CONTACT_CHANNEL_STATES } from '../ui/visual-states';
import { channelStates, contactProblem } from './contact-presentation';
import { ContactTabs } from './contact-tabs';
import { Contact, ContactInput, ContactsApi } from './contacts.api';

type Editing = { kind: 'new' } | { kind: 'edit'; contact: Contact };

/** Who Willay alerts and how. Admin and operator read; only admin changes anything. */
@Component({
  selector: 'app-contacts-page',
  imports: [ReactiveFormsModule, LoadState, Notice, StateBadge, PageHeader, Icon, ContactTabs],
  templateUrl: './contacts-page.html',
})
export class ContactsPage {
  private readonly api = inject(ContactsApi);
  private readonly session = inject(Session);
  protected readonly t = t;

  protected readonly channelLabels = CONTACT_CHANNEL_STATES;
  protected readonly contacts = signal<Contact[]>([]);
  protected readonly loaded = signal(false);
  protected readonly loadFailed = signal(false);
  protected readonly listStatus = computed(() =>
    loadStatus(this.loaded(), this.loadFailed(), this.contacts().length),
  );
  protected readonly editing = signal<Editing | null>(null);
  protected readonly problem = signal<string | null>(null);
  protected readonly saving = signal(false);
  protected readonly status = signal('');
  /** The Telegram link just generated: shown once, like a station's API key. */
  protected readonly link = signal<{ name: string; url: string; expiresAt: string } | null>(null);
  protected readonly copied = signal(false);

  /** Reaching the page by its URL without the permission: explain it instead of a 403. */
  protected readonly canView = computed(
    () => this.session.me()?.permissions.includes('contacts:view_details') ?? false,
  );
  protected readonly canManage = computed(
    () => this.session.me()?.permissions.includes('contacts:manage') ?? false,
  );
  /** "5 contactos · 1 sin canal · 2 sin grupos": who no alert reaches stands out. */
  protected readonly subtitle = computed(() => {
    if (!this.loaded()) return '';
    const contacts = this.contacts();
    const parts = [t('contacts.count', { count: contacts.length })];
    const unreachable = contacts.filter((c) => channelStates(c).includes('none')).length;
    if (unreachable > 0) parts.push(t('contacts.noChannel', { count: unreachable }));
    const ungrouped = contacts.filter((c) => c.groups.length === 0).length;
    if (ungrouped > 0) parts.push(t('contacts.ungrouped', { count: ungrouped }));
    return parts.join(' · ');
  });

  protected readonly form = new FormGroup({
    full_name: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(120)],
    }),
    email: new FormControl('', {
      nonNullable: true,
      validators: [Validators.email, Validators.maxLength(254)],
    }),
    // '' = the organization's language.
    language: new FormControl<Language | ''>('', { nonNullable: true }),
  });
  protected readonly languages = LANGUAGES;
  protected readonly languageNames = LANGUAGE_NAMES;

  constructor() {
    if (this.canView()) this.load();
  }

  protected load(): void {
    this.api.list().subscribe({
      next: (contacts) => {
        this.contacts.set(contacts);
        this.loaded.set(true);
        this.loadFailed.set(false);
      },
      error: () => this.loadFailed.set(true),
    });
  }

  protected channels(contact: Contact) {
    return channelStates(contact);
  }

  protected groupNames(contact: Contact): string {
    return contact.groups.map((group) => group.name).join(', ');
  }

  protected time(iso: string): string {
    return localTime(iso, this.session.me()?.organization_timezone ?? 'UTC');
  }

  protected startCreate(): void {
    this.form.reset();
    this.problem.set(null);
    this.editing.set({ kind: 'new' });
  }

  protected startEdit(contact: Contact): void {
    this.form.setValue({
      full_name: contact.full_name,
      email: contact.email ?? '',
      language: contact.language ?? '',
    });
    this.problem.set(null);
    this.editing.set({ kind: 'edit', contact });
  }

  protected cancel(): void {
    this.editing.set(null);
    this.problem.set(null);
  }

  protected save(): void {
    const editing = this.editing();
    if (!editing) return;
    const value = this.form.getRawValue();
    if (this.form.invalid || !value.full_name.trim()) {
      this.form.markAllAsTouched();
      this.problem.set(t('contacts.invalidForm'));
      return;
    }
    const body: ContactInput = {
      full_name: value.full_name.trim(),
      email: value.email.trim() || null,
      language: value.language || null,
    };
    this.saving.set(true);
    const request =
      editing.kind === 'new' ? this.api.create(body) : this.api.update(editing.contact.id, body);
    request.subscribe({
      next: (contact) => {
        this.saving.set(false);
        this.cancel();
        this.done(
          t(editing.kind === 'new' ? 'contacts.created' : 'contacts.saved', {
            name: contact.full_name,
          }),
        );
      },
      error: (error: unknown) => {
        this.saving.set(false);
        this.problem.set(contactProblem(error));
      },
    });
  }

  protected generateLink(contact: Contact): void {
    const pending = contact.telegram_link_expires_at;
    if (
      pending &&
      !confirm(t('contacts.confirmAnotherLink', { name: contact.full_name }))
    ) {
      return;
    }
    this.api.telegramLink(contact.id).subscribe({
      next: (link) => {
        this.link.set({ name: contact.full_name, url: link.url, expiresAt: link.expires_at });
        this.copied.set(false);
        this.done(t('contacts.linkGenerated', { name: contact.full_name }));
      },
      error: (error: unknown) => this.status.set(contactProblem(error)),
    });
  }

  protected unlinkTelegram(contact: Contact): void {
    if (!confirm(t('contacts.confirmUnlink', { name: contact.full_name }))) return;
    this.api.unlinkTelegram(contact.id).subscribe({
      next: () => this.done(t('contacts.unlinked', { name: contact.full_name })),
      error: (error: unknown) => this.status.set(contactProblem(error)),
    });
  }

  protected remove(contact: Contact): void {
    if (!confirm(t('contacts.confirmDelete', { name: contact.full_name }))) return;
    this.api.delete(contact.id).subscribe({
      next: () => this.done(t('contacts.deleted', { name: contact.full_name })),
      // A 409 means it gained history since the list loaded: say why and show it as it is now.
      error: (error: unknown) => {
        this.status.set(contactProblem(error));
        this.load();
      },
    });
  }

  protected removeFromGroups(contact: Contact): void {
    const groups = contact.groups.map((g) => g.name).join(', ');
    if (!confirm(t('contacts.confirmRemoveFromGroups', { name: contact.full_name, groups }))) return;
    this.api.removeFromGroups(contact.id).subscribe({
      next: () => this.done(t('contacts.removedFromGroups', { name: contact.full_name })),
      error: (error: unknown) => this.status.set(contactProblem(error)),
    });
  }

  protected async copyLink(): Promise<void> {
    const link = this.link();
    if (!link) return;
    await navigator.clipboard.writeText(link.url);
    this.copied.set(true);
  }

  protected dismissLink(): void {
    this.link.set(null);
    this.copied.set(false);
  }

  private done(message: string): void {
    this.status.set(message);
    this.load();
  }
}
