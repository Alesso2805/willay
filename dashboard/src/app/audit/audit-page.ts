import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { t } from '../i18n/i18n';
import { Session } from '../session';
import { localTime } from '../ui/formats';
import { LoadState, loadStatus } from '../ui/load-state';
import { Notice } from '../ui/notice';
import { PageHeader } from '../ui/page-header';
import {
  ENTITY_TYPES,
  actionText,
  actorLabel,
  entityLabel,
  dayStart,
  fieldChanges,
  nextDay,
} from './audit-presentation';
import { AuditApi, AuditEntry, AuditQuery, Author, EntityType } from './audit.api';
import { FieldChanges } from './field-changes';

/** The filters as the URL keeps them: shareable, and kept on reload. */
interface Filters {
  tipo: EntityType | '';
  autor: string;
  desde: string; // YYYY-MM-DD, the organization's day
  hasta: string; // YYYY-MM-DD, inclusive
  entidad: string;
}

const EMPTY: Filters = { tipo: '', autor: '', desde: '', hasta: '', entidad: '' };

/**
 * Who changed what, most recent first. Admin only. Filters live in the URL; "Cargar
 * más" follows the API's cursor, so entries arriving meanwhile neither repeat nor go missing.
 */
@Component({
  selector: 'app-audit-page',
  imports: [LoadState, Notice, PageHeader, FieldChanges],
  templateUrl: './audit-page.html',
})
export class AuditPage {
  private readonly api = inject(AuditApi);
  private readonly session = inject(Session);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly t = t;
  protected readonly entityTypes = ENTITY_TYPES.map((type) => [type, entityLabel(type)] as const);
  protected readonly entries = signal<AuditEntry[]>([]);
  protected readonly authors = signal<Author[]>([]);
  protected readonly cursor = signal<string | null>(null);
  protected readonly loaded = signal(false);
  protected readonly loadFailed = signal(false);
  protected readonly loadingMore = signal(false);
  protected readonly filters = signal<Filters>(EMPTY);
  protected readonly listStatus = computed(() =>
    loadStatus(this.loaded(), this.loadFailed(), this.entries().length),
  );
  protected readonly canView = computed(
    () => this.session.me()?.permissions.includes('audit:view') ?? false,
  );
  protected readonly filtered = computed(() =>
    Object.values(this.filters()).some((value) => value !== ''),
  );
  /** An inverted range would get a 422: it is explained by the date fields instead. */
  protected readonly dateProblem = computed(() => {
    const { desde, hasta } = this.filters();
    // Both are YYYY-MM-DD, so comparing the text compares the days.
    return desde && hasta && hasta < desde ? t('audit.dateOrder') : null;
  });
  protected readonly actor = actorLabel;
  protected readonly action = actionText;
  /** Each request numbered: an answer for older filters is ignored. */
  private request = 0;

  constructor() {
    if (!this.canView()) return;
    this.api.authors().subscribe({ next: (authors) => this.authors.set(authors) });
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      this.filters.set({
        tipo: (params.get('tipo') as EntityType | null) ?? '',
        autor: params.get('autor') ?? '',
        desde: params.get('desde') ?? '',
        hasta: params.get('hasta') ?? '',
        entidad: params.get('entidad') ?? '',
      });
      this.load();
    });
  }

  protected load(): void {
    const request = ++this.request;
    this.loaded.set(false);
    this.loadFailed.set(false);
    if (this.dateProblem()) return; // also when the URL comes with the range inverted
    this.api.page(this.query(), null).subscribe({
      next: (page) => {
        if (request !== this.request) return;
        this.entries.set(page.items);
        this.cursor.set(page.next_cursor);
        this.loaded.set(true);
      },
      error: () => {
        if (request === this.request) this.loadFailed.set(true);
      },
    });
  }

  protected loadMore(): void {
    const cursor = this.cursor();
    if (!cursor) return;
    const request = this.request;
    this.loadingMore.set(true);
    this.api.page(this.query(), cursor).subscribe({
      next: (page) => {
        this.loadingMore.set(false);
        if (request !== this.request) return;
        this.entries.update((entries) => [...entries, ...page.items]);
        this.cursor.set(page.next_cursor);
      },
      error: () => this.loadingMore.set(false),
    });
  }

  protected setFilter(key: keyof Filters, value: string): void {
    const next = { ...this.filters(), [key]: value };
    void this.router.navigate([], {
      queryParams: Object.fromEntries(Object.entries(next).map(([k, v]) => [k, v || null])),
    });
  }

  protected clearFilters(): void {
    void this.router.navigate([], { queryParams: {} });
  }

  protected time(iso: string): string {
    return localTime(iso, this.timezone(), true);
  }

  protected changes(entry: AuditEntry) {
    return fieldChanges(entry, this.timezone());
  }

  private timezone(): string {
    return this.session.me()?.organization_timezone ?? 'UTC';
  }

  private query(): AuditQuery {
    const f = this.filters();
    const zone = this.timezone();
    return {
      entity_type: f.tipo || undefined,
      actor_id: f.autor || undefined,
      entity_id: f.entidad || undefined,
      // The organization's days: from the start of "desde" to the end of "hasta".
      since: f.desde ? dayStart(f.desde, zone) : undefined,
      until: f.hasta ? dayStart(nextDay(f.hasta), zone) : undefined,
    };
  }
}
