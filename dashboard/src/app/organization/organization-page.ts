import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { startWith } from 'rxjs';
import { LANGUAGES, LANGUAGE_NAMES, Language, t } from '../i18n/i18n';
import { Session } from '../session';
import { clock } from '../ui/clock';
import { localTime } from '../ui/formats';
import { LoadState, loadStatus } from '../ui/load-state';
import { Notice } from '../ui/notice';
import { PageHeader } from '../ui/page-header';
import { Organization, OrganizationApi } from './organization.api';

/** Every IANA name the browser knows, plus the saved one if it does not know that one. */
export function timezoneOptions(current: string, known: readonly string[]): string[] {
  return known.includes(current) ? [...known] : [current, ...known];
}

function knownTimezones(): string[] {
  return typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : [];
}

/**
 * VIG-44: how Willay writes for the organization. Its language is the one of the alerts of its
 * contacts that chose none; its time zone, the one of every time in emails, Telegram and here.
 * Every role may read it; only an admin saves it.
 */
@Component({
  selector: 'app-organization-page',
  imports: [ReactiveFormsModule, LoadState, Notice, PageHeader],
  template: `
    <app-page-header
      [title]="t('organization.title')"
      [subtitle]="organization() ? t('organization.subtitle', { name: organization()!.name }) : ''"
    />
    @if (status() !== 'ready') {
      <app-load-state
        [status]="status()"
        [loading]="t('organization.loading')"
        [empty]="''"
        [error]="t('organization.loadFailed')"
        (retry)="load()"
      />
    } @else {
      <form class="card max-w-2xl space-y-5 p-5" [formGroup]="form" (ngSubmit)="save()">
        @if (!canManage()) {
          <app-notice tone="info">{{ t('organization.readOnly') }}</app-notice>
        }
        <div>
          <label for="organization-language" class="block text-sm font-medium text-ink">
            {{ t('organization.language') }}
          </label>
          <select
            id="organization-language"
            class="field mt-1 w-full max-w-xs"
            formControlName="language"
            aria-describedby="organization-language-help"
          >
            @for (language of languages; track language) {
              <option [value]="language" [attr.lang]="language">
                {{ languageNames[language] }}
              </option>
            }
          </select>
          <p id="organization-language-help" class="mt-1 text-sm text-ink-muted">
            {{ t('organization.languageHelp') }}
          </p>
        </div>
        <div>
          <label for="organization-timezone" class="block text-sm font-medium text-ink">
            {{ t('organization.timezone') }}
          </label>
          <select
            id="organization-timezone"
            class="field mt-1 w-full max-w-xs"
            formControlName="timezone"
            aria-describedby="organization-timezone-help"
          >
            @for (timezone of timezones(); track timezone) {
              <option [value]="timezone">{{ timezone }}</option>
            }
          </select>
          <p id="organization-timezone-help" class="mt-1 text-sm text-ink-muted">
            {{ t('organization.timezoneHelp', { now: nowThere() }) }}
          </p>
        </div>
        @if (problem(); as problem) {
          <app-notice>{{ problem }}</app-notice>
        }
        @if (canManage()) {
          <div class="flex flex-wrap items-center gap-3">
            <button type="submit" class="btn-primary" [disabled]="saving()">
              {{ t('organization.save') }}
            </button>
            <p role="status" class="text-sm text-ink-muted">{{ saved() }}</p>
          </div>
        }
      </form>
    }
  `,
})
export class OrganizationPage {
  private readonly api = inject(OrganizationApi);
  private readonly session = inject(Session);
  protected readonly t = t;
  protected readonly languages = LANGUAGES;
  protected readonly languageNames = LANGUAGE_NAMES;

  protected readonly organization = signal<Organization | null>(null);
  private readonly failed = signal(false);
  protected readonly status = computed(() =>
    loadStatus(this.organization() !== null, this.failed(), 1),
  );
  protected readonly saving = signal(false);
  protected readonly saved = signal('');
  protected readonly problem = signal<string | null>(null);
  protected readonly canManage = computed(
    () => this.session.me()?.permissions.includes('organization:manage') ?? false,
  );

  protected readonly form = new FormGroup({
    language: new FormControl<Language>('es', { nonNullable: true }),
    timezone: new FormControl('America/Lima', { nonNullable: true }),
  });
  private readonly picked = toSignal(
    this.form.controls.timezone.valueChanges.pipe(startWith(this.form.controls.timezone.value)),
    { initialValue: this.form.controls.timezone.value },
  );
  private readonly now = clock(30_000);
  /** The time there right now: picking a zone shows at once what it means. */
  protected readonly nowThere = computed(() =>
    localTime(new Date(this.now()).toISOString(), this.picked()),
  );
  protected readonly timezones = computed(() =>
    timezoneOptions(this.organization()?.timezone ?? 'America/Lima', knownTimezones()),
  );

  constructor() {
    this.load();
  }

  protected load(): void {
    this.failed.set(false);
    this.api.get().subscribe({
      next: (organization) => this.show(organization),
      error: () => this.failed.set(true),
    });
  }

  protected save(): void {
    if (!this.canManage()) return;
    const { language, timezone } = this.form.getRawValue();
    this.saving.set(true);
    this.problem.set(null);
    this.saved.set('');
    this.api.update(language, timezone).subscribe({
      next: (organization) => {
        this.saving.set(false);
        this.show(organization);
        // Every time on screen follows the new zone without signing in again.
        this.session.useOrganizationTimezone(organization.timezone);
        this.saved.set(t('organization.saved'));
      },
      error: (error: unknown) => {
        this.saving.set(false);
        this.problem.set(problemText(error));
      },
    });
  }

  private show(organization: Organization): void {
    this.organization.set(organization);
    this.form.setValue({ language: organization.language, timezone: organization.timezone });
    if (!this.canManage()) this.form.disable();
  }
}

function problemText(error: unknown): string {
  if (!(error instanceof HttpErrorResponse)) return t('ui.genericProblem');
  if (error.status === 403) return t('organization.forbidden');
  const first = Array.isArray(error.error?.detail) ? error.error.detail[0] : null;
  if (error.status === 422 && typeof first?.msg === 'string') return first.msg;
  return t('organization.saveFailed');
}
