import { Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { t } from '../i18n/i18n';
import { causeLabel, incidentState } from '../incidents/incident-presentation';
import { Incident } from '../incidents/incidents.api';
import { liveSnapshot } from '../realtime/live-snapshot';
import { Session } from '../session';
import { ageText, localTime, measurement } from '../ui/formats';
import { LoadState, loadStatus } from '../ui/load-state';
import { PageHeader } from '../ui/page-header';
import { StateBadge } from '../ui/state-badge';
import { INCIDENT_STATES, STATION_STATES, StationState, ZONE_STATES } from '../ui/visual-states';
import { riskLabel } from '../zones/zone-presentation';
import { Zone } from '../zones/zones.api';
import { LiveMap } from './live-map';
import {
  StationView,
  ZONE_URGENCY,
  ZoneView,
  byStationUrgency,
  incidentSummary,
  stationIncidentStates,
  stationView,
  zoneStates,
} from './live-map-presentation';

/**
 * "Mapa en vivo": zones by the state of their active incidents and stations with their
 * last value and its age, kept current by the live channel. The lists next to the map say the
 * same in words, for keyboards, screen readers and narrow screens.
 */
@Component({
  selector: 'app-live-map-page',
  imports: [LiveMap, LoadState, PageHeader, StateBadge, RouterLink],
  templateUrl: './live-map-page.html',
})
export class LiveMapPage {
  private readonly session = inject(Session);
  private readonly snapshot = liveSnapshot();

  protected readonly zoneStates = ZONE_STATES;
  protected readonly stationStates = STATION_STATES;
  protected readonly incidentStates = INCIDENT_STATES;
  protected readonly zoneLegend = ZONE_URGENCY;
  protected readonly stationLegend: readonly StationState[] = [
    'reporting',
    'silent',
    'unzoned',
    'waiting',
  ];
  protected readonly cause = causeLabel;
  protected readonly stateOf = incidentState;

  protected readonly status = computed(() => {
    const data = this.snapshot.data();
    const count = (data?.zones.length ?? 0) + (data?.stations.length ?? 0);
    return loadStatus(data !== null, this.snapshot.failed(), count);
  });

  // Heartbeats replace `data` but keep these arrays, so the zones below (and their polygons on
  // the map) are recomputed only when an incident or a zone changes.
  private readonly incidents = computed(() => this.snapshot.data()?.incidents);
  private readonly zoneList = computed(() => this.snapshot.data()?.zones);

  protected readonly incidentsByZone = computed(() => {
    const byZone = new Map<string, Incident[]>();
    for (const incident of this.incidents() ?? []) {
      byZone.set(incident.zone_id, [...(byZone.get(incident.zone_id) ?? []), incident]);
    }
    return byZone;
  });

  /** Most urgent first. */
  protected readonly zones = computed<ZoneView[]>(() => {
    const states = zoneStates(this.incidents() ?? []);
    const byZone = this.incidentsByZone();
    return (this.zoneList() ?? [])
      .map((zone) => ({
        zone,
        state: states.get(zone.id) ?? 'calm',
        summary: incidentSummary(byZone.get(zone.id) ?? []),
      }))
      .sort(
        (a, b) =>
          ZONE_URGENCY.indexOf(b.state) - ZONE_URGENCY.indexOf(a.state) ||
          a.zone.name.localeCompare(b.zone.name),
      );
  });

  private readonly stationIncidents = computed(() => stationIncidentStates(this.incidents() ?? []));

  /** Most urgent first: silent, without a zone, waiting, reporting. */
  protected readonly stations = computed<StationView[]>(() => {
    const asOf = this.snapshot.asOf();
    const now = this.snapshot.now();
    const incidents = this.stationIncidents();
    return (this.snapshot.data()?.stations ?? [])
      .map((station) => stationView(station, asOf, now, incidents.get(station.id) ?? null))
      .sort(byStationUrgency);
  });

  /** "3 zonas · 1 con incidentes activos · 6 de 7 estaciones reportando". */
  protected readonly subtitle = computed(() => {
    if (!this.snapshot.data()) return '';
    const zones = this.zones();
    const stations = this.stations();
    const troubled = zones.filter((view) => view.state !== 'calm').length;
    const reporting = stations.filter(
      (view) => view.marker === 'reporting' || view.secondary === 'reporting',
    ).length;
    return [
      t('map.zones', { count: zones.length }),
      t('map.troubled', { count: troubled }),
      t('map.reporting', { reporting, total: stations.length }),
    ].join(' · ');
  });

  protected readonly t = t;

  protected load(): void {
    this.snapshot.load();
  }

  protected risk(zone: Zone): string {
    return riskLabel(zone.risk_level).toLowerCase();
  }

  protected number(value: number): string {
    return measurement(value);
  }

  protected age(iso: string): string {
    return ageText(iso, this.snapshot.now());
  }

  /** Exact time in the organization's time zone, for the `title` of the age. */
  protected time(iso: string): string {
    return localTime(iso, this.session.me()?.organization_timezone ?? 'UTC');
  }
}
