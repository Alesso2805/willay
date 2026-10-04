import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { EMPTY, Subject, catchError, map, merge, switchMap } from 'rxjs';
import { t } from '../i18n/i18n';
import { LiveEvents } from '../realtime/live-events';
import { Session } from '../session';
import { clock } from '../ui/clock';
import { ageText, localTime } from '../ui/formats';
import { LoadState, loadStatus } from '../ui/load-state';
import { PageHeader } from '../ui/page-header';
import { StateBadge } from '../ui/state-badge';
import { INCIDENT_STATES, SEVERITIES } from '../ui/visual-states';
import {
  InboxFilter,
  SEVERITY_OPTIONS,
  STATUS_OPTIONS,
  filterFromUrl,
  filterToUrl,
} from './inbox-filter';
import { causeLabel, incidentState } from './incident-presentation';
import { Incident, IncidentSeverity, IncidentStatus, IncidentsApi } from './incidents.api';

/** Enough for an inbox; older incidents are found by narrowing the filters. */
export const INBOX_LIMIT = 200;

/**
 * Incident inbox (VIG-34): the organization's incidents, newest first, filtered by status and
 * severity from the URL. It follows the live channel; new incidents are announced by the shell
 * on every page (NewIncidents), so this page does not announce them again.
 */
@Component({
  selector: 'app-incidents-page',
  imports: [PageHeader, LoadState, StateBadge, RouterLink],
  templateUrl: './incidents-page.html',
})
export class IncidentsPage {
  private readonly api = inject(IncidentsApi);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly session = inject(Session);

  protected readonly statusOptions = STATUS_OPTIONS;
  protected readonly severityOptions = SEVERITY_OPTIONS;
  protected readonly incidentStates = INCIDENT_STATES;
  protected readonly severities = SEVERITIES;
  protected readonly t = t;
  protected readonly exhaustedColor = INCIDENT_STATES.exhausted.background;
  protected readonly cause = causeLabel;
  protected readonly stateOf = incidentState;
  protected readonly limit = INBOX_LIMIT;

  protected readonly filter = toSignal(this.route.queryParamMap.pipe(map(filterFromUrl)), {
    requireSync: true,
  });
  protected readonly incidents = signal<Incident[] | null>(null);
  protected readonly failed = signal(false);
  private readonly now = clock(10_000);
  private readonly retries = new Subject<void>();

  protected readonly status = computed(() =>
    loadStatus(this.incidents() !== null, this.failed(), this.incidents()?.length ?? 0),
  );
  /** "3 incidentes · 1 con escalamiento agotado". */
  protected readonly summary = computed(() => {
    const incidents = this.incidents();
    if (!incidents) return '';
    const parts = [t('incidents.count', { count: incidents.length })];
    const exhausted = incidents.filter((incident) => incidentState(incident) === 'exhausted');
    if (exhausted.length > 0) parts.push(t('incidents.exhausted', { count: exhausted.length }));
    return parts.join(' · ');
  });

  protected readonly announcement = computed(() => {
    const incidents = this.incidents();
    if (!incidents) return '';
    return incidents.length > 0 ? this.summary() : t('incidents.empty');
  });

  constructor() {
    const live = inject(LiveEvents);
    // switchMap: only the latest list counts, even if an older request answers later.
    merge(toObservable(this.filter), live.reload$, live.incidents$, this.retries)
      .pipe(
        switchMap(() => {
          const { statuses, severities } = this.filter();
          return this.api.list(statuses, severities, INBOX_LIMIT).pipe(
            catchError(() => {
              this.failed.set(true);
              return EMPTY;
            }),
          );
        }),
        takeUntilDestroyed(),
      )
      .subscribe((incidents) => {
        this.incidents.set(incidents);
        this.failed.set(false);
      });
  }

  protected retry(): void {
    this.retries.next();
  }

  protected toggleStatus(status: IncidentStatus, checked: boolean): void {
    const { statuses } = this.filter();
    this.navigate({
      ...this.filter(),
      statuses: checked ? [...statuses, status] : statuses.filter((s) => s !== status),
    });
  }

  protected toggleSeverity(severity: IncidentSeverity, checked: boolean): void {
    const { severities } = this.filter();
    this.navigate({
      ...this.filter(),
      severities: checked ? [...severities, severity] : severities.filter((s) => s !== severity),
    });
  }

  /** At least one status stays checked: with none, the inbox would fall back to its default. */
  protected isLastStatus(status: IncidentStatus): boolean {
    const { statuses } = this.filter();
    return statuses.length === 1 && statuses[0] === status;
  }

  protected time(iso: string): string {
    return localTime(iso, this.session.me()?.organization_timezone ?? 'UTC');
  }

  protected age(iso: string): string {
    return ageText(iso, this.now());
  }

  private navigate(filter: InboxFilter): void {
    // replaceUrl: ticking filters does not fill the back button's history.
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: filterToUrl(filter),
      replaceUrl: true,
    });
  }
}
