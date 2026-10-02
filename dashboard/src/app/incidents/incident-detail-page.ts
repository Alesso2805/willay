import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { EMPTY, Subject, catchError, filter, map, merge, switchMap } from 'rxjs';
import { LiveEvents } from '../realtime/live-events';
import { Session } from '../session';
import { localTime } from '../ui/formats';
import { Notice } from '../ui/notice';
import { PageHeader } from '../ui/page-header';
import { StateBadge } from '../ui/state-badge';
import { INCIDENT_STATES, SEVERITIES } from '../ui/visual-states';
import { causeLabel, incidentState } from './incident-presentation';
import { IncidentDetail, IncidentsApi } from './incidents.api';
import { eventText } from './timeline-presentation';

type DetailState =
  | { status: 'loading' }
  | { status: 'ready'; incident: IncidentDetail }
  | { status: 'not-found' }
  | { status: 'error' };

/**
 * An incident's detail (VIG-26): summary and timeline. It reloads when one of its own events
 * arrives on the live channel and after every reconnection.
 */
@Component({
  selector: 'app-incident-detail-page',
  imports: [RouterLink, Notice, PageHeader, StateBadge],
  templateUrl: './incident-detail-page.html',
})
export class IncidentDetailPage {
  private readonly api = inject(IncidentsApi);
  private readonly session = inject(Session);

  protected readonly incidentStates = INCIDENT_STATES;
  protected readonly severities = SEVERITIES;
  protected readonly stateOf = incidentState;
  protected readonly text = eventText;

  protected readonly state = signal<DetailState>({ status: 'loading' });
  protected readonly incident = computed(() => {
    const state = this.state();
    return state.status === 'ready' ? state.incident : null;
  });
  /** "Estación sin reportar · RIM-SEU-01". */
  protected readonly title = computed(() => {
    const incident = this.incident();
    if (!incident) return 'Incidente';
    const cause = causeLabel(incident.rule_type);
    return incident.station_code ? `${cause} · ${incident.station_code}` : cause;
  });
  /** Who acknowledged, from the timeline: the incident only keeps their id. */
  protected readonly acknowledgedBy = computed(() => {
    const event = this.incident()?.timeline.find((e) => e.event_type === 'acknowledged');
    return event?.actor_name ?? null;
  });
  private readonly retries = new Subject<void>();

  constructor() {
    const route = inject(ActivatedRoute);
    const live = inject(LiveEvents);
    const id$ = route.paramMap.pipe(map((params) => params.get('id') ?? ''));
    id$
      .pipe(
        switchMap((id) => {
          this.state.set({ status: 'loading' });
          // Its own events (acknowledged, escalated…), reconnections and retries reload it.
          const changes = merge(
            live.incidents$.pipe(filter((change) => change.incidentId === id)),
            live.reload$,
            this.retries,
          );
          return merge([undefined], changes).pipe(
            switchMap(() =>
              this.api.get(id).pipe(
                catchError((error: unknown) => {
                  this.failed(error);
                  return EMPTY;
                }),
              ),
            ),
          );
        }),
        takeUntilDestroyed(),
      )
      .subscribe((incident) => this.state.set({ status: 'ready', incident }));
  }

  protected retry(): void {
    this.retries.next();
  }

  protected time(iso: string, seconds = false): string {
    return localTime(iso, this.session.me()?.organization_timezone ?? 'UTC', seconds);
  }

  /** A failed reload keeps what is on screen: the live channel brings the next one. */
  private failed(error: unknown): void {
    if (error instanceof HttpErrorResponse && error.status === 404) {
      this.state.set({ status: 'not-found' });
    } else if (this.state().status !== 'ready') {
      this.state.set({ status: 'error' });
    }
  }
}
