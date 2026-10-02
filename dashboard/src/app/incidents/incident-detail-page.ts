import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { EMPTY, Subject, catchError, filter, forkJoin, map, merge, switchMap } from 'rxjs';
import { LiveEvents } from '../realtime/live-events';
import { Session } from '../session';
import { localTime } from '../ui/formats';
import { Notice } from '../ui/notice';
import { PageHeader } from '../ui/page-header';
import { StateBadge } from '../ui/state-badge';
import { ALERT_STATES, INCIDENT_STATES, SEVERITIES } from '../ui/visual-states';
import { causeLabel, incidentState } from './incident-presentation';
import { IncidentAlert, IncidentDetail, IncidentReadings, IncidentsApi } from './incidents.api';
import { ChartMark, ReadingsChart } from './readings-chart';
import { eventText } from './timeline-presentation';

type DetailState =
  | { status: 'loading' }
  | { status: 'ready'; incident: IncidentDetail; alerts: IncidentAlert[]; readings: IncidentReadings }
  | { status: 'not-found' }
  | { status: 'error' };

const CHANNELS: Record<IncidentAlert['channel'], string> = { email: 'Correo', telegram: 'Telegram' };

/**
 * An incident's detail (VIG-26): summary, alerts by recipient and timeline. It reloads when
 * one of its own events arrives on the live channel and after every reconnection.
 */
@Component({
  selector: 'app-incident-detail-page',
  imports: [RouterLink, Notice, PageHeader, StateBadge, ReadingsChart],
  templateUrl: './incident-detail-page.html',
})
export class IncidentDetailPage {
  private readonly api = inject(IncidentsApi);
  private readonly session = inject(Session);

  protected readonly incidentStates = INCIDENT_STATES;
  protected readonly alertStates = ALERT_STATES;
  protected readonly channels = CHANNELS;
  protected readonly severities = SEVERITIES;
  protected readonly stateOf = incidentState;
  protected readonly text = eventText;

  protected readonly state = signal<DetailState>({ status: 'loading' });
  protected readonly incident = computed(() => {
    const state = this.state();
    return state.status === 'ready' ? state.incident : null;
  });
  protected readonly alerts = computed(() => {
    const state = this.state();
    return state.status === 'ready' ? state.alerts : [];
  });
  protected readonly readings = computed(() => {
    const state = this.state();
    return state.status === 'ready' ? state.readings : null;
  });
  protected readonly timezone = computed(() => this.session.me()?.organization_timezone ?? 'UTC');
  /** The moments that tell the incident's story on the chart. */
  protected readonly marks = computed<ChartMark[]>(() => {
    const incident = this.incident();
    if (!incident) return [];
    const marks = [{ at: incident.opened_at, label: 'Apertura' }];
    if (incident.acknowledged_at) marks.push({ at: incident.acknowledged_at, label: 'Confirmación' });
    if (incident.resolved_at) marks.push({ at: incident.resolved_at, label: 'Resolución' });
    return marks;
  });
  /** Alerts grouped by escalation level, in order (the cards on narrow screens). */
  protected readonly alertLevels = computed(() => {
    const state = this.state();
    if (state.status !== 'ready') return [];
    const levels = new Map<number, IncidentAlert[]>();
    for (const alert of state.alerts) {
      levels.set(alert.level_order, [...(levels.get(alert.level_order) ?? []), alert]);
    }
    return [...levels].map(([level, alerts]) => ({ level, alerts }));
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
              forkJoin({
                incident: this.api.get(id),
                alerts: this.api.alerts(id),
                readings: this.api.readings(id),
              }).pipe(
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
      .subscribe((loaded) => this.state.set({ status: 'ready', ...loaded }));
  }

  /** "Confirmó el 02/10/2026 00:30" or "Enviada el …"; null if it never went out. */
  protected when(alert: IncidentAlert): string | null {
    if (alert.acknowledged_at) return `Confirmó el ${this.time(alert.acknowledged_at)}`;
    if (alert.sent_at) return `Enviada el ${this.time(alert.sent_at)}`;
    return null;
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
