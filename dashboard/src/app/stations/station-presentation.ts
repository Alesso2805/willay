import { HttpErrorResponse } from '@angular/common/http';
import { t } from '../i18n/i18n';
import { StationState } from '../ui/visual-states';
import { Heartbeat, Station, Variable, ZonePosition } from './stations.api';

export const VARIABLES: readonly Variable[] = ['discharge', 'water_level', 'rainfall'];

export function variableLabel(variable: Variable): string {
  return t(`variables.${variable}`);
}

/** Mirrors the backend rule: the unit follows from the variable (it is not chosen). */
export const UNITS: Record<Variable, string> = {
  discharge: 'm3/s',
  water_level: 'm',
  rainfall: 'mm',
};

export const POSITIONS: readonly ZonePosition[] = ['upstream', 'in_zone', 'downstream'];

export function positionLabel(position: ZonePosition): string {
  return t(`positions.${position}`);
}

/**
 * Whether the station is reporting or silent, with the same rule as the `silence` worker: no
 * batches for K × expected interval, judged at `now`, which callers take from `dataTime`: the
 * browser clock while the live channel is up, the newest data otherwise. It is an approximate
 * view; the worker opens the incident. An inactive station is `inactive`. A station that never
 * reported is not silent (SPEC: it has not started transmitting yet), so it has no state:
 * returns null.
 */
export function stationState(station: Station, now: number): StationState | null {
  if (station.status === 'inactive') return 'inactive';
  if (station.heartbeat === null) return null;
  const silentAfterMs = station.expected_interval_s * station.silence_multiplier * 1000;
  return now - Date.parse(station.heartbeat.last_seen_at) > silentAfterMs ? 'silent' : 'reporting';
}

/**
 * The stations with a live heartbeat applied. Like `station_heartbeats` in the database, a
 * heartbeat never goes backwards: an older one (an event overtaken by a REST response) is
 * ignored, and so is a station that is not in the list.
 */
export function withHeartbeat(stations: Station[], stationId: string, heartbeat: Heartbeat): Station[] {
  return stations.map((station) =>
    station.id === stationId && notOlder(heartbeat, station.heartbeat)
      ? { ...station, heartbeat }
      : station,
  );
}

/**
 * A fresh REST list, keeping any heartbeat the page already has that is newer: an event can
 * arrive while the request is in flight, and the response must not undo it.
 */
export function keepNewerHeartbeats(fresh: Station[], current: Station[]): Station[] {
  const known = new Map(current.map((station) => [station.id, station.heartbeat]));
  return fresh.map((station) => {
    const heartbeat = known.get(station.id);
    return heartbeat && notOlder(heartbeat, station.heartbeat)
      ? { ...station, heartbeat }
      : station;
  });
}

function notOlder(candidate: Heartbeat, current: Heartbeat | null): boolean {
  return current === null || Date.parse(candidate.last_seen_at) >= Date.parse(current.last_seen_at);
}

export function stationSaveProblem(error: unknown): string {
  if (!(error instanceof HttpErrorResponse)) return t('stations.saveFailed');
  if (error.status === 409) return t('stations.duplicate');
  if (error.status === 403) return t('stations.forbidden');
  if (error.status === 422) {
    const detail = error.error?.detail;
    const first = Array.isArray(detail) ? detail[0] : null;
    return typeof first?.msg === 'string' ? first.msg : t('ui.invalidData');
  }
  return t('stations.saveRetry');
}
