import { IconName } from './icon';

/**
 * Single catalog of the dashboard's visual states (VIG-33). No page defines state colors on
 * its own: they come from here.
 *
 * Every state is conveyed with text and an icon, never by color alone (WCAG 1.4.1). Colors
 * are hex rather than Tailwind classes so a test can measure their contrast:
 * - `foreground` on `background`: ≥ 4.5:1 (label text and icon);
 * - `map` on white: ≥ 3:1 (strokes and markers on the map).
 */
export interface VisualState {
  label: string;
  icon: IconName;
  foreground: string;
  background: string;
  map: string;
}

const RED = { foreground: '#991b1b', background: '#fee2e2', map: '#b91c1c' };
const ORANGE = { foreground: '#9a3412', background: '#ffedd5', map: '#c2410c' };
const AMBER = { foreground: '#92400e', background: '#fef3c7', map: '#a16207' };
const GREEN = { foreground: '#166534', background: '#dcfce7', map: '#15803d' };
const BLUE = { foreground: '#1e40af', background: '#dbeafe', map: '#1d4ed8' };
const SLATE = { foreground: '#334155', background: '#f1f5f9', map: '#475569' };
/** Inverted: the one thing that must stand out even with red all around. */
const ALARM = { foreground: '#ffffff', background: '#991b1b', map: '#7f1d1d' };

export type IncidentState = 'open' | 'acknowledged' | 'resolved' | 'exhausted';
export type Severity = 'info' | 'warning' | 'critical';
export type RiskLevelKey = 'low' | 'medium' | 'high' | 'critical';
export type StationState = 'reporting' | 'silent' | 'unzoned' | 'inactive' | 'waiting';
export type ZoneState = 'calm' | 'acknowledged' | 'open' | 'exhausted';
export type AlertState = 'pending' | 'sent' | 'failed' | 'skipped' | 'acknowledged';
export type ContactChannelState = 'email' | 'telegram' | 'pending' | 'none';

/** `exhausted`: open with nobody acknowledging at any level (SPEC: shown in red). */
export const INCIDENT_STATES: Readonly<Record<IncidentState, VisualState>> = {
  open: { label: 'Abierto', icon: 'bell', ...ORANGE },
  acknowledged: { label: 'Confirmado', icon: 'check', ...BLUE },
  resolved: { label: 'Resuelto', icon: 'check-circle', ...SLATE },
  exhausted: { label: 'Escalamiento agotado', icon: 'octagon-x', ...ALARM },
};

export const SEVERITIES: Readonly<Record<Severity, VisualState>> = {
  info: { label: 'Informativo', icon: 'info', ...BLUE },
  warning: { label: 'Advertencia', icon: 'triangle-alert', ...AMBER },
  critical: { label: 'Crítico', icon: 'octagon-alert', ...RED },
};

/** The icon's bars grow with the level: the order also reads without color. */
export const RISK_LEVEL_STATES: Readonly<Record<RiskLevelKey, VisualState>> = {
  low: { label: 'Bajo', icon: 'level-1', ...GREEN },
  medium: { label: 'Medio', icon: 'level-2', ...AMBER },
  high: { label: 'Alto', icon: 'level-3', ...ORANGE },
  critical: { label: 'Crítico', icon: 'level-4', ...RED },
};

export const STATION_STATES: Readonly<Record<StationState, VisualState>> = {
  reporting: { label: 'Reportando', icon: 'signal', ...GREEN },
  silent: { label: 'Sin reportar', icon: 'signal-off', ...RED },
  unzoned: { label: 'Sin zona', icon: 'pin-off', ...AMBER },
  inactive: { label: 'Inactiva', icon: 'pause', ...SLATE },
  /** Never reported: it has not started transmitting yet, so it is not silent (SPEC). */
  waiting: { label: 'Sin lecturas', icon: 'clock', ...SLATE },
};

/** A zone on the live map (VIG-25) shows its most urgent active incident. */
export const ZONE_STATES: Readonly<Record<ZoneState, VisualState>> = {
  calm: { label: 'Sin incidentes', icon: 'check-circle', ...GREEN },
  acknowledged: { label: 'Incidente confirmado', icon: 'check', ...BLUE },
  open: { label: 'Incidente abierto', icon: 'bell', ...ORANGE },
  exhausted: { label: 'Escalamiento agotado', icon: 'octagon-x', ...ALARM },
};

/** One alert to one recipient through one channel (VIG-26). */
export const ALERT_STATES: Readonly<Record<AlertState, VisualState>> = {
  pending: { label: 'Pendiente', icon: 'clock', ...SLATE },
  sent: { label: 'Enviada', icon: 'check', ...BLUE },
  failed: { label: 'Falló', icon: 'octagon-x', ...RED },
  skipped: { label: 'Omitida', icon: 'pause', ...AMBER },
  acknowledged: { label: 'Confirmó', icon: 'check-circle', ...GREEN },
};

/** How a contact can be reached (VIG-36); one that cannot is flagged, since no alert reaches it. */
export const CONTACT_CHANNEL_STATES: Readonly<Record<ContactChannelState, VisualState>> = {
  email: { label: 'Correo', icon: 'mail', ...BLUE },
  telegram: { label: 'Telegram', icon: 'send', ...BLUE },
  pending: { label: 'Enlace de Telegram pendiente', icon: 'clock', ...SLATE },
  none: { label: 'Sin canal', icon: 'triangle-alert', ...AMBER },
};

export type ConnectionState = 'connecting' | 'live' | 'reconnecting';

/** The live channel (VIG-25): while it is down, what the dashboard shows may be stale. */
export const CONNECTION_STATES: Readonly<Record<ConnectionState, VisualState>> = {
  connecting: { label: 'Conectando…', icon: 'refresh', ...SLATE },
  live: { label: 'En vivo', icon: 'broadcast', ...GREEN },
  reconnecting: { label: 'Sin conexión en vivo', icon: 'signal-off', ...AMBER },
};

/** UI notices (errors, warnings): not states, but pages do not pick their colors either. */
export type NoticeTone = 'error' | 'warning' | 'info';

export const NOTICE_TONES: Readonly<
  Record<NoticeTone, { foreground: string; background: string; border: string }>
> = {
  error: { foreground: '#7f1d1d', background: '#fef2f2', border: '#fca5a5' },
  warning: { foreground: '#78350f', background: '#fffbeb', border: '#fbbf24' },
  info: { foreground: '#1e293b', background: '#f8fafc', border: '#cbd5e1' },
};

export const ALL_CATALOGS = {
  incident: INCIDENT_STATES,
  severity: SEVERITIES,
  risk: RISK_LEVEL_STATES,
  station: STATION_STATES,
  zone: ZONE_STATES,
  alert: ALERT_STATES,
  contactChannel: CONTACT_CHANNEL_STATES,
  connection: CONNECTION_STATES,
} as const;
