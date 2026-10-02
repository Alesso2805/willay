import { actionText, actorLabel, dayStart, fieldChanges, nextDay } from './audit-presentation';
import { AuditEntry } from './audit.api';

const ENTRY: AuditEntry = {
  id: 1,
  at: '2026-10-02T22:03:11Z',
  actor: { id: 'u1', name: 'Óscar Operador Rímac' },
  entity_type: 'rule',
  entity_id: 'r1',
  entity_name: null,
  action: 'update',
  before: {
    type: 'threshold',
    zone: 'Chosica',
    station: 'RIM-CHO-02',
    params: { operator: 'ge', value: 9999, consecutive: 2 },
    cooldown_s: 300,
    is_active: true,
  },
  after: {
    type: 'threshold',
    zone: 'Chosica',
    station: 'RIM-CHO-02',
    params: { operator: 'ge', value: 9999, consecutive: 4 },
    cooldown_s: 300,
    is_active: false,
  },
};

describe('actionText', () => {
  it('says what was done to what, with the name it had then', () => {
    expect(actionText(ENTRY)).toBe('Editó la regla Chosica · RIM-CHO-02');
    expect(
      actionText({ ...ENTRY, action: 'create', after: { ...ENTRY.after!, station: null } }),
    ).toBe('Creó la regla Chosica · toda la zona');
    const contact: AuditEntry = {
      ...ENTRY,
      entity_type: 'contact',
      action: 'removed_from_groups',
      after: { full_name: 'Rosa Brigada' },
    };
    expect(actionText(contact)).toBe('Quitó de sus grupos al contacto Rosa Brigada');
    expect(actionText({ ...contact, action: 'telegram_unlinked' })).toBe(
      'Desvinculó el Telegram del contacto Rosa Brigada',
    );
    const station: AuditEntry = {
      ...ENTRY,
      entity_type: 'station',
      action: 'rotate_api_key',
      after: { code: 'RIM-CHA-01' },
    };
    expect(actionText(station)).toBe('Rotó la API key de la estación RIM-CHA-01');
  });
});

describe('actorLabel', () => {
  it('names the user, or the contact themselves when nobody from the organization did it', () => {
    expect(actorLabel(ENTRY)).toBe('Óscar Operador Rímac');
    expect(
      actorLabel({ ...ENTRY, actor: null, entity_type: 'contact', action: 'telegram_linked' }),
    ).toBe('El propio contacto');
  });
});

describe('fieldChanges', () => {
  it('lists only what changed, per field, readably', () => {
    expect(fieldChanges(ENTRY)).toEqual([
      {
        field: 'Parámetros',
        before: 'condición: mayor o igual que, límite: 9999, lecturas seguidas: 2',
        after: 'condición: mayor o igual que, límite: 9999, lecturas seguidas: 4',
      },
      { field: 'Activa', before: 'Sí', after: 'No' },
    ]);
  });

  it('says coded values in the words the dashboard uses', () => {
    const created: AuditEntry = {
      ...ENTRY,
      action: 'create',
      before: null,
      after: { type: 'rate_of_change', severity: 'critical', status: 'active' },
    };
    expect(fieldChanges(created).map((c) => c.after)).toEqual([
      'Cambio brusco',
      'Crítico',
      'Activa',
    ]);
  });

  it('shows what something was created with, and a polygon as a word', () => {
    const zone: AuditEntry = {
      ...ENTRY,
      entity_type: 'risk_zone',
      action: 'create',
      before: null,
      after: {
        name: 'Chosica',
        geometry: { type: 'MultiPolygon', coordinates: [] },
        population_estimate: null,
      },
    };
    expect(fieldChanges(zone)).toEqual([
      { field: 'Nombre', before: '—', after: 'Chosica' },
      { field: 'Polígono', before: '—', after: 'polígono' },
    ]);
  });
});

describe('an entry whose snapshot has no name', () => {
  const link: AuditEntry = {
    ...ENTRY,
    entity_type: 'contact',
    entity_id: '01a0fdd6-0000-7000-8000-000000000000',
    action: 'telegram_link_created',
    before: { telegram_link_expires_at: null },
    after: { telegram_link_expires_at: '2026-10-09T18:17:56.284061+00:00' },
  };

  it('uses the entity current name, or a short id once it is gone', () => {
    expect(actionText({ ...link, entity_name: 'Rosa Brigada' })).toBe(
      'Generó el enlace de Telegram del contacto Rosa Brigada',
    );
    expect(actionText(link)).toBe('Generó el enlace de Telegram del contacto 01a0fdd6');
  });

  it('shows instants in the organization time', () => {
    expect(fieldChanges(link, 'America/Lima')).toEqual([
      { field: 'Enlace de Telegram válido hasta', before: '—', after: '09/10/2026 13:17' },
    ]);
  });
});

describe('days in the organization time zone', () => {
  it('starts a Lima day at 05:00 UTC, and an inclusive end becomes the next day', () => {
    expect(dayStart('2026-10-02', 'America/Lima')).toBe('2026-10-02T05:00:00.000Z');
    expect(dayStart('2026-10-02', 'UTC')).toBe('2026-10-02T00:00:00.000Z');
    expect(nextDay('2026-12-31')).toBe('2027-01-01');
  });
});
