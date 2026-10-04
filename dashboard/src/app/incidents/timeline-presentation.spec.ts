import { useLanguage } from '../i18n/i18n';
import { IncidentEvent } from './incidents.api';
import { eventText } from './timeline-presentation';

function event(event_type: string, payload: Record<string, unknown> = {}, extra: Partial<IncidentEvent> = {}): IncidentEvent {
  return {
    id: 1,
    occurred_at: '2026-10-02T03:31:03Z',
    event_type,
    actor_type: 'system',
    actor_id: null,
    actor_name: null,
    contact_name: null,
    payload,
    ...extra,
  };
}

const text = (e: IncidentEvent) => {
  const { title, detail } = eventText(e);
  return detail ? `${title} | ${detail}` : title;
};

describe('timeline presentation', () => {
  it('tells the timeline in English too', async () => {
    await useLanguage('en');
    expect(
      text(
        event('opened', {
          rule_type: 'threshold',
          rule_params: { operator: 'gt', value: 3.5, consecutive: 2 },
          trigger_value: 4.6,
        }),
      ),
    ).toBe('The incident opened | Rule: more than 3.5 in 2 readings in a row · value 4.6');
    expect(
      text(event('opened', { rule_type: 'silence', rule_params: {}, trigger_value: 85.2 })),
    ).toBe('The incident opened | Rule: the station stopped reporting · last value 85.2');
    expect(
      text(event('alert_sent', { channel: 'email', level_order: 2 }, { contact_name: 'Rosa' })),
    ).toBe('Alert sent to Rosa by email | level 2');
    expect(text(event('acknowledged', {}, { actor_type: 'contact', actor_name: 'Rosa' }))).toBe(
      'Acknowledged by Rosa | From their alert',
    );
  });

  it('says how the incident opened, with its rule and value', () => {
    expect(
      text(
        event('opened', {
          rule_type: 'threshold',
          rule_params: { operator: 'gt', value: 3.5, consecutive: 2 },
          trigger_value: 4.6,
        }),
      ),
    ).toBe('Se abrió el incidente | Regla: más de 3.5 en 2 lecturas seguidas · valor 4.6');
    expect(
      text(
        event('opened', {
          rule_type: 'rate_of_change',
          rule_params: { direction: 'down', delta: 40, window_minutes: 10 },
          trigger_value: 41.25,
        }),
      ),
    ).toBe('Se abrió el incidente | Regla: bajada de más de 40 en 10 min · valor 41.25');
    expect(text(event('opened', { rule_type: 'silence', trigger_value: 82.1 }))).toBe(
      'Se abrió el incidente | Regla: la estación dejó de reportar · último valor 82.1',
    );
  });

  it('names who was alerted, through which channel and why not', () => {
    const toRosa = { contact_name: 'Rosa Brigada' };
    expect(text(event('alert_sent', { channel: 'email', level_order: 2 }, toRosa))).toBe(
      'Alerta enviada a Rosa Brigada por correo | nivel 2',
    );
    expect(
      text(event('alert_skipped', { channel: 'telegram', reason: 'el contacto no vinculó Telegram' }, toRosa)),
    ).toBe('No se avisó a Rosa Brigada por Telegram | el contacto no vinculó Telegram');
    expect(text(event('alert_failed', { channel: 'email', level_order: 1 }, toRosa))).toBe(
      'Falló un envío a Rosa Brigada por correo; se reintentará | nivel 1',
    );
    expect(text(event('alert_failed', { channel: 'email', final: true, level_order: 1 }, toRosa))).toBe(
      'No se pudo avisar a Rosa Brigada por correo | nivel 1',
    );
    expect(text(event('alert_sent', { channel: 'email' }))).toBe('Alerta enviada a un contacto por correo');
  });

  it('tells the escalation, the recovery and who acknowledged or resolved', () => {
    expect(text(event('escalated', { to_level: 2, reason: 'nadie confirmó en 120 s' }))).toBe(
      'Escaló al nivel 2 | nadie confirmó en 120 s',
    );
    expect(text(event('escalation_exhausted', { reason: 'nadie confirmó en 300 s' }))).toBe(
      'Se agotó el escalamiento | nadie confirmó en 300 s',
    );
    expect(text(event('station_recovered'))).toBe('La estación volvió a reportar');
    expect(text(event('reading_added', { value: 4.9 }))).toBe('Empeoró: nueva lectura de 4.9');
    expect(
      text(event('acknowledged', {}, { actor_type: 'contact', actor_name: 'Rosa Brigada' })),
    ).toBe('Confirmado por Rosa Brigada | Desde su alerta');
    expect(text(event('acknowledged', {}, { actor_type: 'user', actor_name: 'Óscar' }))).toBe(
      'Confirmado por Óscar',
    );
    expect(
      text(event('resolved', { resolution: 'false_alarm' }, { actor_type: 'user', actor_name: 'Óscar' })),
    ).toBe('Marcado como falsa alarma por Óscar');
    expect(text(event('comment', { text: 'Bajamos a revisar' }, { actor_name: 'Óscar' }))).toBe(
      'Comentario de Óscar | Bajamos a revisar',
    );
    expect(text(event('something_new'))).toBe('something_new');
  });
});
