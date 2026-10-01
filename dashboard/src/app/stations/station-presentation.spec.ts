import { HttpErrorResponse } from '@angular/common/http';
import {
  keepNewerHeartbeats,
  stationProblem,
  stationState,
  withHeartbeat,
} from './station-presentation';
import { Heartbeat, Station } from './stations.api';

const STATION: Station = {
  id: 's1',
  code: 'RIM-SEU-01',
  name: 'Santa Eulalia',
  variable: 'discharge',
  unit: 'm3/s',
  location: { type: 'Point', coordinates: [-76.66, -11.9] },
  source: 'simulator',
  expected_interval_s: 10,
  silence_multiplier: 3,
  status: 'active',
  has_zone: true,
  zones: [],
  heartbeat: {
    last_seen_at: '2026-10-27T08:59:30Z',
    last_measured_at: '2026-10-27T08:59:30Z',
    last_value: 83.2,
  },
  api_key_rotated_at: '2026-10-01T00:00:00Z',
  created_at: '2026-10-01T00:00:00Z',
};

describe('station presentation', () => {
  const now = Date.parse('2026-10-27T09:00:00Z');

  it('a station is silent after K × its expected interval without reporting', () => {
    expect(stationState(STATION, now)).toBe('reporting'); // 30 s: exactly at the limit
    expect(stationState(STATION, now + 1000)).toBe('silent');
  });

  it('a station that never reported has not started, and an inactive one is inactive', () => {
    expect(stationState({ ...STATION, heartbeat: null }, now)).toBeNull();
    expect(stationState({ ...STATION, status: 'inactive' }, now)).toBe('inactive');
  });

  it('a live heartbeat updates its station, but never with an older one', () => {
    const newer: Heartbeat = { ...STATION.heartbeat!, last_seen_at: '2026-10-27T08:59:40Z', last_value: 90 };
    const older: Heartbeat = { ...STATION.heartbeat!, last_seen_at: '2026-10-27T08:59:20Z', last_value: 70 };
    const other = { ...STATION, id: 's2' };

    expect(withHeartbeat([STATION, other], 's1', newer)).toEqual([{ ...STATION, heartbeat: newer }, other]);
    expect(withHeartbeat([STATION], 's1', older)).toEqual([STATION]);
    expect(withHeartbeat([{ ...STATION, heartbeat: null }], 's1', older)[0].heartbeat).toEqual(older);
    expect(withHeartbeat([STATION], 'unknown', newer)).toEqual([STATION]);
  });

  it('a REST list does not undo a heartbeat that arrived while it was in flight', () => {
    const live: Heartbeat = { ...STATION.heartbeat!, last_seen_at: '2026-10-27T08:59:40Z', last_value: 90 };
    const later: Heartbeat = { ...STATION.heartbeat!, last_seen_at: '2026-10-27T08:59:50Z', last_value: 95 };
    const current = [{ ...STATION, heartbeat: live }];

    expect(keepNewerHeartbeats([STATION], current)[0].heartbeat).toEqual(live);
    expect(keepNewerHeartbeats([{ ...STATION, heartbeat: later }], current)[0].heartbeat).toEqual(later);
    expect(keepNewerHeartbeats([{ ...STATION, id: 'new' }], current)[0].id).toBe('new');
  });

  it('explains a duplicate code and passes 422 reasons through', () => {
    expect(stationProblem(new HttpErrorResponse({ status: 409 }))).toContain('ese código');
    const unknownZone = new HttpErrorResponse({
      status: 422,
      error: { detail: [{ loc: ['body', 'zones'], msg: 'zonas desconocidas: [...]' }] },
    });
    expect(stationProblem(unknownZone)).toBe('zonas desconocidas: [...]');
  });
});
