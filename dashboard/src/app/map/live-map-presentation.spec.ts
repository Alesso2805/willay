import { causeLabel, incidentState } from '../incidents/incident-presentation';
import { Incident } from '../incidents/incidents.api';
import { Station } from '../stations/stations.api';
import { byStationUrgency, stationView, zoneStates } from './live-map-presentation';

const NOW = Date.parse('2026-10-02T09:00:00Z');

function incident(zone_id: string, status: Incident['status'], exhausted = false): Incident {
  return {
    id: crypto.randomUUID(),
    zone_id,
    zone_name: 'Z',
    station_id: null,
    station_code: null,
    rule_type: 'threshold',
    severity: 'critical',
    status,
    current_level: 1,
    opened_at: '2026-10-02T08:00:00Z',
    escalation_exhausted_at: exhausted ? '2026-10-02T08:30:00Z' : null,
  };
}

function station(code: string, seenSecondsAgo: number | null, hasZone = true): Station {
  const seen = seenSecondsAgo === null ? null : new Date(NOW - seenSecondsAgo * 1000).toISOString();
  return {
    id: code,
    code,
    name: `Estación ${code}`,
    variable: 'discharge',
    unit: 'm3/s',
    location: { type: 'Point', coordinates: [-76.7, -11.9] },
    source: 'simulator',
    expected_interval_s: 10,
    silence_multiplier: 3,
    status: 'active',
    zones: [],
    has_zone: hasZone,
    heartbeat: seen ? { last_seen_at: seen, last_measured_at: seen, last_value: 83.2 } : null,
    api_key_rotated_at: '',
    created_at: '',
  };
}

describe('incident presentation', () => {
  it('uses the same cause wording as the alert emails', () => {
    expect(causeLabel('silence')).toBe('Estación sin reportar');
    expect(causeLabel('rate_of_change')).toBe('Cambio brusco');
    expect(causeLabel('threshold')).toBe('Valor fuera de límite');
  });

  it('shows an exhausted escalation only while nobody has acknowledged', () => {
    expect(incidentState(incident('z', 'open', true))).toBe('exhausted');
    expect(incidentState(incident('z', 'acknowledged', true))).toBe('acknowledged');
    expect(incidentState(incident('z', 'open'))).toBe('open');
  });
});

describe('live map presentation', () => {
  it('a zone shows its most urgent active incident; one without any is calm', () => {
    const states = zoneStates([
      incident('a', 'acknowledged'),
      incident('a', 'open'),
      incident('b', 'acknowledged'),
      incident('c', 'open', true),
      incident('c', 'acknowledged'),
      incident('d', 'resolved'),
    ]);
    expect(states.get('a')).toBe('open');
    expect(states.get('b')).toBe('acknowledged');
    expect(states.get('c')).toBe('exhausted');
    expect(states.has('d')).toBe(false); // calm
  });

  it('a marker tells reporting, silent, waiting and zoneless stations apart', () => {
    expect(stationView(station('A', 5), NOW, NOW).marker).toBe('reporting');
    expect(stationView(station('B', 600), NOW, NOW).marker).toBe('silent');
    expect(stationView(station('C', null), NOW, NOW).marker).toBe('waiting'); // not silent: it never started
    const zoneless = stationView(station('D', 600, false), NOW, NOW);
    expect(zoneless.marker).toBe('unzoned');
    expect(zoneless.secondary).toBe('silent');
  });

  it('the tooltip says code, name, last value with its age, and state', () => {
    expect(stationView(station('RIM-SEU-01', 12), NOW, NOW).label).toBe(
      'RIM-SEU-01 · Estación RIM-SEU-01 · 83.2 m3/s hace 12 s · Reportando',
    );
    expect(stationView(station('X', 600, false), NOW, NOW).label).toContain('Sin zona · Sin reportar');
  });

  it('judges silence against asOf but ages against the clock', () => {
    const view = stationView(station('A', 600), NOW - 590_000, NOW); // data complete only up to 10 min ago
    expect(view.marker).toBe('reporting');
    expect(view.label).toContain('hace 10 min');
  });

  it('lists the most urgent stations first', () => {
    const views = [station('B', 5), station('A', 5), station('Z', 600), station('W', null)].map((s) =>
      stationView(s, NOW, NOW),
    );
    expect(views.sort(byStationUrgency).map((v) => v.station.code)).toEqual(['Z', 'W', 'A', 'B']);
  });
});
