import { TranslationKey, t } from '../i18n/i18n';
import { incidentState } from '../incidents/incident-presentation';
import { Incident } from '../incidents/incidents.api';
import { stationState } from '../stations/station-presentation';
import { Station } from '../stations/stations.api';
import { ageText, valueWithUnit } from '../ui/formats';
import { iconSvg } from '../ui/icon';
import { STATION_STATES, StationState, ZONE_STATES, ZoneState } from '../ui/visual-states';
import { Zone } from '../zones/zones.api';

/** An active incident as the map shows it: acknowledged, open or with its escalation exhausted. */
export type ActiveIncidentState = Exclude<ZoneState, 'calm'>;

/** From least to most urgent: a zone shows its most urgent active incident. */
export const ZONE_URGENCY: readonly ZoneState[] = ['calm', 'acknowledged', 'open', 'exhausted'];

export interface ZoneView {
  zone: Zone;
  state: ZoneState;
  /** Its active incidents by state: "1 con escalamiento agotado · 2 confirmados". */
  summary: string;
}

/** The most urgent active incident per key (zone or station); without any, the key is missing. */
function mostUrgent(
  incidents: readonly Incident[],
  keyOf: (incident: Incident) => string | null,
): Map<string, ActiveIncidentState> {
  const states = new Map<string, ActiveIncidentState>();
  for (const incident of incidents) {
    const key = keyOf(incident);
    const state = incidentState(incident);
    if (key === null || state === 'resolved') continue;
    const current = states.get(key);
    if (!current || ZONE_URGENCY.indexOf(state) > ZONE_URGENCY.indexOf(current)) {
      states.set(key, state);
    }
  }
  return states;
}

/** By zone id; a zone with no active incident is missing from the result: it is calm. */
export function zoneStates(incidents: readonly Incident[]): Map<string, ZoneState> {
  return mostUrgent(incidents, (incident) => incident.zone_id);
}

/**
 * By station id: the badge on its marker. A zone keeps the color of its most urgent incident,
 * so acknowledging one incident may not change the zone; the badge shows it on that station.
 */
export function stationIncidentStates(
  incidents: readonly Incident[],
): Map<string, ActiveIncidentState> {
  return mostUrgent(incidents, (incident) => incident.station_id);
}

const COUNT_KEYS: Readonly<Record<ActiveIncidentState, TranslationKey>> = {
  exhausted: 'map.count.exhausted',
  open: 'map.count.open',
  acknowledged: 'map.count.acknowledged',
};

/** A zone's active incidents counted by state, most urgent first, or "Sin incidentes". */
export function incidentSummary(incidents: readonly Incident[]): string {
  const counts = new Map<ActiveIncidentState, number>();
  for (const incident of incidents) {
    const state = incidentState(incident);
    if (state !== 'resolved') counts.set(state, (counts.get(state) ?? 0) + 1);
  }
  const parts = (['exhausted', 'open', 'acknowledged'] as const).flatMap((state) => {
    const count = counts.get(state) ?? 0;
    return count === 0 ? [] : [t(COUNT_KEYS[state], { count })];
  });
  return parts.length > 0 ? parts.join(' · ') : t(ZONE_STATES.calm.labelKey);
}

/**
 * The stroke also grows with urgency, so a zone's state reads without color too; the tooltip
 * and the list next to the map say it in words.
 */
export const ZONE_STYLES: Readonly<
  Record<ZoneState, { weight: number; dashArray?: string; fillOpacity: number }>
> = {
  calm: { weight: 1, dashArray: '4 4', fillOpacity: 0.05 },
  acknowledged: { weight: 2, fillOpacity: 0.15 },
  open: { weight: 3, fillOpacity: 0.25 },
  exhausted: { weight: 4, fillOpacity: 0.35 },
};

/** From most to least urgent, to sort the station list. */
const STATION_URGENCY: readonly StationState[] = ['silent', 'unzoned', 'waiting', 'reporting', 'inactive'];

export interface StationView {
  station: Station;
  /** What its marker shows. */
  marker: StationState;
  /** For a station without a zone (what its marker shows), whether it reports. */
  secondary: StationState | null;
  /** Its most urgent active incident: the badge on the marker. */
  incident: ActiveIncidentState | null;
  /** Tooltip text: code, name, last value and age, state, incident. */
  label: string;
}

/**
 * A station on the live map. Without a zone it cannot raise alerts, which matters more here than
 * whether it reports; one that never reported is waiting, not silent (SPEC).
 */
export function stationView(
  station: Station,
  asOf: number,
  now: number,
  incident: ActiveIncidentState | null = null,
): StationView {
  const reporting = stationState(station, asOf);
  const marker: StationState = !station.has_zone ? 'unzoned' : (reporting ?? 'waiting');
  const parts = [station.code, station.name];
  const heartbeat = station.heartbeat;
  if (heartbeat?.last_value !== null && heartbeat?.last_value !== undefined) {
    const value = valueWithUnit(heartbeat.last_value, station.unit);
    parts.push(`${value} ${ageText(heartbeat.last_measured_at, now)}`);
  }
  parts.push(t(STATION_STATES[marker].labelKey));
  const secondary = marker === 'unzoned' ? reporting : null;
  if (secondary) parts.push(t(STATION_STATES[secondary].labelKey));
  if (incident) parts.push(t(ZONE_STATES[incident].labelKey));
  return { station, marker, secondary, incident, label: parts.join(' · ') };
}

export function byStationUrgency(a: StationView, b: StationView): number {
  const urgency = STATION_URGENCY.indexOf(a.marker) - STATION_URGENCY.indexOf(b.marker);
  return urgency || a.station.code.localeCompare(b.station.code);
}

/**
 * A station marker: a circle in its state's color with that state's icon in white and, if the
 * station has an active incident, a badge in the corner with the incident's icon. Icons tell the
 * states apart without color; Leaflet renders this HTML as the marker.
 */
export function markerHtml(state: StationState, incident: ActiveIncidentState | null): string {
  const look = STATION_STATES[state];
  const badge = incident
    ? `<span class="absolute -top-2.5 -right-2.5 grid size-5 place-items-center rounded-full ` +
      `border-2 border-white" style="background-color:${ZONE_STATES[incident].map}">` +
      `${iconSvg(ZONE_STATES[incident].icon, 12)}</span>`
    : '';
  return (
    `<span class="relative grid size-7 place-items-center rounded-full border-2 border-white ` +
    `text-white shadow-md" style="background-color:${look.map}">` +
    `${iconSvg(look.icon, 16)}${badge}</span>`
  );
}
