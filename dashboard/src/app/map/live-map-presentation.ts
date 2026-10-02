import { incidentState } from '../incidents/incident-presentation';
import { Incident } from '../incidents/incidents.api';
import { stationState } from '../stations/station-presentation';
import { Station } from '../stations/stations.api';
import { ageText, valueWithUnit } from '../ui/formats';
import { STATION_STATES, StationState, ZoneState } from '../ui/visual-states';
import { Zone } from '../zones/zones.api';

/** From least to most urgent: a zone shows its most urgent active incident. */
export const ZONE_URGENCY: readonly ZoneState[] = ['calm', 'acknowledged', 'open', 'exhausted'];

export interface ZoneView {
  zone: Zone;
  state: ZoneState;
}

/** By zone id; a zone with no active incident is missing from the result: it is calm. */
export function zoneStates(incidents: readonly Incident[]): Map<string, ZoneState> {
  const states = new Map<string, ZoneState>();
  for (const incident of incidents) {
    const state = incidentState(incident);
    if (state === 'resolved') continue;
    const current = states.get(incident.zone_id) ?? 'calm';
    if (ZONE_URGENCY.indexOf(state) > ZONE_URGENCY.indexOf(current)) {
      states.set(incident.zone_id, state);
    }
  }
  return states;
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
  /** Tooltip text: code, name, last value and age, state. */
  label: string;
}

/**
 * A station on the live map. Without a zone it cannot raise alerts, which matters more here than
 * whether it reports; one that never reported is waiting, not silent (SPEC).
 */
export function stationView(station: Station, asOf: number, now: number): StationView {
  const reporting = stationState(station, asOf);
  const marker: StationState = !station.has_zone ? 'unzoned' : (reporting ?? 'waiting');
  const parts = [station.code, station.name];
  const heartbeat = station.heartbeat;
  if (heartbeat?.last_value !== null && heartbeat?.last_value !== undefined) {
    const value = valueWithUnit(heartbeat.last_value, station.unit);
    parts.push(`${value} ${ageText(heartbeat.last_measured_at, now)}`);
  }
  parts.push(STATION_STATES[marker].label);
  const secondary = marker === 'unzoned' ? reporting : null;
  if (secondary) parts.push(STATION_STATES[secondary].label);
  return { station, marker, secondary, label: parts.join(' · ') };
}

export function byStationUrgency(a: StationView, b: StationView): number {
  const urgency = STATION_URGENCY.indexOf(a.marker) - STATION_URGENCY.indexOf(b.marker);
  return urgency || a.station.code.localeCompare(b.station.code);
}
