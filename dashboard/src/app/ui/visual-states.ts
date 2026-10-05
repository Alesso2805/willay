import { TranslationKey } from '../i18n/i18n';
import { IconName } from './icon';

/**
 * Single catalog of the dashboard's visual states (VIG-33). No page defines state colors on
 * its own: they come from here.
 *
 * Every state is conveyed with text and an icon, never by color alone (WCAG 1.4.1). A state
 * names a tone, whose shades live in styles.css as CSS variables, one set per theme (VIG-41):
 * switching themes recolors every badge, notice and marker without redrawing anything. The
 * catalog test reads styles.css and measures both themes:
 * - `foreground` on `background`: ≥ 4.5:1 (label text and icon);
 * - `map` on the base map and under a white icon: ≥ 3:1 (strokes and markers).
 */
export type Tone = 'red' | 'orange' | 'amber' | 'green' | 'blue' | 'slate' | 'alarm';

export interface VisualState {
  /** Translated where it is drawn: `t(state.labelKey)`. */
  labelKey: TranslationKey;
  icon: IconName;
  tone: Tone;
  /** CSS colors for inline styles, in the current theme: `var(--tone-…)`. */
  foreground: string;
  background: string;
  map: string;
}

function tone(name: Tone): Pick<VisualState, 'tone' | 'foreground' | 'background' | 'map'> {
  return {
    tone: name,
    foreground: `var(--tone-${name}-fg)`,
    background: `var(--tone-${name}-bg)`,
    map: `var(--tone-${name}-map)`,
  };
}

/**
 * The class that colors a Leaflet path (a zone, a circle marker) in a state's tone, or in a
 * tone itself. SVG `stroke` and `fill` attributes cannot take a CSS variable, so styles.css
 * colors these classes instead.
 */
export function toneClass(state: VisualState | Tone): string {
  return `tone-${typeof state === 'string' ? state : state.tone}`;
}

const RED = tone('red');
const ORANGE = tone('orange');
const AMBER = tone('amber');
const GREEN = tone('green');
const BLUE = tone('blue');
const SLATE = tone('slate');
/** Inverted: the one thing that must stand out even with red all around. */
const ALARM = tone('alarm');

export type IncidentState = 'open' | 'acknowledged' | 'resolved' | 'exhausted';
export type Severity = 'info' | 'warning' | 'critical';
export type RiskLevelKey = 'low' | 'medium' | 'high' | 'critical';
export type StationState = 'reporting' | 'silent' | 'unzoned' | 'inactive' | 'waiting';
export type ZoneState = 'calm' | 'acknowledged' | 'open' | 'exhausted';
export type AlertState = 'pending' | 'sent' | 'failed' | 'skipped' | 'acknowledged';
export type ContactChannelState = 'email' | 'telegram' | 'pending' | 'none';
export type GroupState = 'empty' | 'unused';
export type RuleState = 'inactive';

/** `exhausted`: open with nobody acknowledging at any level (SPEC: shown in red). */
export const INCIDENT_STATES: Readonly<Record<IncidentState, VisualState>> = {
  open: { labelKey: 'states.incident.open', icon: 'bell', ...ORANGE },
  acknowledged: { labelKey: 'states.incident.acknowledged', icon: 'check', ...BLUE },
  resolved: { labelKey: 'states.incident.resolved', icon: 'check-circle', ...SLATE },
  exhausted: { labelKey: 'states.incident.exhausted', icon: 'octagon-x', ...ALARM },
};

export const SEVERITIES: Readonly<Record<Severity, VisualState>> = {
  info: { labelKey: 'states.severity.info', icon: 'info', ...BLUE },
  warning: { labelKey: 'states.severity.warning', icon: 'triangle-alert', ...AMBER },
  critical: { labelKey: 'states.severity.critical', icon: 'octagon-alert', ...RED },
};

/** The icon's bars grow with the level: the order also reads without color. */
export const RISK_LEVEL_STATES: Readonly<Record<RiskLevelKey, VisualState>> = {
  low: { labelKey: 'states.risk.low', icon: 'level-1', ...GREEN },
  medium: { labelKey: 'states.risk.medium', icon: 'level-2', ...AMBER },
  high: { labelKey: 'states.risk.high', icon: 'level-3', ...ORANGE },
  critical: { labelKey: 'states.risk.critical', icon: 'level-4', ...RED },
};

export const STATION_STATES: Readonly<Record<StationState, VisualState>> = {
  reporting: { labelKey: 'states.station.reporting', icon: 'signal', ...GREEN },
  silent: { labelKey: 'states.station.silent', icon: 'signal-off', ...RED },
  unzoned: { labelKey: 'states.station.unzoned', icon: 'pin-off', ...AMBER },
  inactive: { labelKey: 'states.station.inactive', icon: 'pause', ...SLATE },
  /** Never reported: it has not started transmitting yet, so it is not silent (SPEC). */
  waiting: { labelKey: 'states.station.waiting', icon: 'clock', ...SLATE },
};

/** A zone on the live map (VIG-25) shows its most urgent active incident. */
export const ZONE_STATES: Readonly<Record<ZoneState, VisualState>> = {
  calm: { labelKey: 'states.zone.calm', icon: 'check-circle', ...GREEN },
  acknowledged: { labelKey: 'states.zone.acknowledged', icon: 'check', ...BLUE },
  open: { labelKey: 'states.zone.open', icon: 'bell', ...ORANGE },
  exhausted: { labelKey: 'states.zone.exhausted', icon: 'octagon-x', ...ALARM },
};

/** One alert to one recipient through one channel (VIG-26). */
export const ALERT_STATES: Readonly<Record<AlertState, VisualState>> = {
  pending: { labelKey: 'states.alert.pending', icon: 'clock', ...SLATE },
  sent: { labelKey: 'states.alert.sent', icon: 'check', ...BLUE },
  failed: { labelKey: 'states.alert.failed', icon: 'octagon-x', ...RED },
  skipped: { labelKey: 'states.alert.skipped', icon: 'pause', ...AMBER },
  acknowledged: { labelKey: 'states.alert.acknowledged', icon: 'check-circle', ...GREEN },
};

/** How a contact can be reached (VIG-36); one that cannot is flagged, since no alert reaches it. */
export const CONTACT_CHANNEL_STATES: Readonly<Record<ContactChannelState, VisualState>> = {
  email: { labelKey: 'states.contactChannel.email', icon: 'mail', ...BLUE },
  telegram: { labelKey: 'states.contactChannel.telegram', icon: 'send', ...BLUE },
  pending: { labelKey: 'states.contactChannel.pending', icon: 'clock', ...SLATE },
  none: { labelKey: 'states.contactChannel.none', icon: 'triangle-alert', ...AMBER },
};

/** A group whose alerts reach nobody (VIG-36): no members, or no policy notifies it. */
export const GROUP_STATES: Readonly<Record<GroupState, VisualState>> = {
  empty: { labelKey: 'states.group.empty', icon: 'triangle-alert', ...AMBER },
  unused: { labelKey: 'states.group.unused', icon: 'pause', ...SLATE },
};

/** A deactivated rule (VIG-27): kept because incidents point to it, but it no longer fires. */
export const RULE_STATES: Readonly<Record<RuleState, VisualState>> = {
  inactive: { labelKey: 'states.rule.inactive', icon: 'pause', ...SLATE },
};

export type ConnectionState = 'connecting' | 'live' | 'reconnecting';

/** The live channel (VIG-25): while it is down, what the dashboard shows may be stale. */
export const CONNECTION_STATES: Readonly<Record<ConnectionState, VisualState>> = {
  connecting: { labelKey: 'states.connection.connecting', icon: 'refresh', ...SLATE },
  live: { labelKey: 'states.connection.live', icon: 'broadcast', ...GREEN },
  reconnecting: { labelKey: 'states.connection.reconnecting', icon: 'signal-off', ...AMBER },
};

/** UI notices (errors, warnings): not states, but pages do not pick their colors either. */
export type NoticeTone = 'error' | 'warning' | 'info';

export const NOTICE_TONES: Readonly<
  Record<NoticeTone, { foreground: string; background: string; border: string }>
> = {
  error: notice('error'),
  warning: notice('warning'),
  info: notice('info'),
};

function notice(name: NoticeTone): { foreground: string; background: string; border: string } {
  return {
    foreground: `var(--notice-${name}-fg)`,
    background: `var(--notice-${name}-bg)`,
    border: `var(--notice-${name}-border)`,
  };
}

export const ALL_CATALOGS = {
  incident: INCIDENT_STATES,
  severity: SEVERITIES,
  risk: RISK_LEVEL_STATES,
  station: STATION_STATES,
  zone: ZONE_STATES,
  alert: ALERT_STATES,
  contactChannel: CONTACT_CHANNEL_STATES,
  group: GROUP_STATES,
  rule: RULE_STATES,
  connection: CONNECTION_STATES,
} as const;
