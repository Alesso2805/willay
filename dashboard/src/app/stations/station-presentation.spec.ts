import { HttpErrorResponse } from '@angular/common/http';
import { stationProblem, stationState } from './station-presentation';
import { Station } from './stations.api';

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
    expect(stationState(STATION, now)).toBe('reporting'); // 30 s: justo en el límite
    expect(stationState(STATION, now + 1000)).toBe('silent');
  });

  it('a station that never reported has not started, and an inactive one is inactive', () => {
    expect(stationState({ ...STATION, heartbeat: null }, now)).toBeNull();
    expect(stationState({ ...STATION, status: 'inactive' }, now)).toBe('inactive');
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
