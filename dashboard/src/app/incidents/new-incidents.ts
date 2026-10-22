import { Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, filter, map, mergeMap, of } from 'rxjs';
import { t } from '../i18n/i18n';
import { LiveEvents } from '../realtime/live-events';
import { Session } from '../session';
import { localTime } from '../ui/formats';
import { Icon } from '../ui/icon';
import { StateBadge } from '../ui/state-badge';
import { INCIDENT_STATES, SEVERITIES } from '../ui/visual-states';
import { causeLabel } from './incident-presentation';
import { Incident, IncidentsApi } from './incidents.api';

interface Announcement {
  id: string;
  /** null: the incident opened but its details could not be loaded. */
  incident: Incident | null;
}

/**
 * Announces every new incident on every page, visibly and to screen readers, until
 * the operator closes it. The live event only carries the id: the incident is fetched over REST,
 * so the viewer's permissions apply. If that fails it is still announced: in an alerting tool,
 * silence would be worse than a notice without details.
 */
@Component({
  selector: 'app-new-incidents',
  imports: [RouterLink, Icon, StateBadge],
  template: `
    <!-- Always in the DOM: screen readers only announce changes to a live region that already exists. -->
    <div aria-live="assertive" class="flex flex-col gap-2" [class.mb-6]="announcements().length > 0">
      @for (item of announcements(); track item.id) {
        <!-- Narrow screens: the text on its own row, the badge and actions below it. -->
        <div
          class="flex flex-col gap-2 rounded-md border-2 p-3 text-sm sm:flex-row sm:items-center sm:gap-3"
          [style.color]="tone.foreground"
          [style.background-color]="tone.background"
          [style.border-color]="tone.map"
        >
          <p class="flex min-w-0 flex-1 items-start gap-2">
            <app-icon class="mt-0.5" name="bell" [size]="18" />
            <span>
              @if (item.incident; as incident) {
                <strong>{{ t('incidents.announce.title', { zone: incident.zone_name }) }}</strong>
                {{ summary(incident) }}
              } @else {
                <strong>{{ t('incidents.announce.unknownTitle') }}</strong>
                {{ t('incidents.announce.unknownBody') }}
              }
            </span>
          </p>
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1 pl-6 sm:pl-0">
            @if (item.incident; as incident) {
              <app-state-badge [state]="severities[incident.severity]" />
            }
            <a [routerLink]="['/incidentes', item.id]" class="font-medium underline">
              {{ t('incidents.announce.view') }}
            </a>
            <button
              type="button"
              class="font-medium underline"
              [attr.aria-label]="
                item.incident
                  ? t('incidents.announce.dismissZone', { zone: item.incident.zone_name })
                  : t('incidents.announce.dismissUnknown')
              "
              (click)="dismiss(item.id)"
            >
              {{ t('incidents.announce.dismiss') }}
            </button>
          </div>
        </div>
      }
    </div>
  `,
})
export class NewIncidents {
  private readonly api = inject(IncidentsApi);
  private readonly session = inject(Session);

  protected readonly tone = INCIDENT_STATES.open;
  protected readonly severities = SEVERITIES;
  protected readonly t = t;
  /** Newest first. */
  protected readonly announcements = signal<Announcement[]>([]);

  constructor() {
    inject(LiveEvents)
      .incidents$.pipe(
        filter((change) => change.event === 'opened'),
        mergeMap((change) =>
          this.api.get(change.incidentId).pipe(
            map((incident): Announcement => ({ id: change.incidentId, incident })),
            catchError(() => of<Announcement>({ id: change.incidentId, incident: null })),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((item) =>
        this.announcements.update((items) =>
          items.some((known) => known.id === item.id) ? items : [item, ...items],
        ),
      );
  }

  /** "Estación sin reportar · RIM-SEU-01 · 02/10/2026 21:40", in the organization's time. */
  protected summary(incident: Incident): string {
    const timezone = this.session.me()?.organization_timezone ?? 'UTC';
    const parts = [causeLabel(incident.rule_type)];
    if (incident.station_code) parts.push(incident.station_code);
    parts.push(localTime(incident.opened_at, timezone));
    return parts.join(' · ');
  }

  protected dismiss(id: string): void {
    this.announcements.update((items) => items.filter((item) => item.id !== id));
  }
}
