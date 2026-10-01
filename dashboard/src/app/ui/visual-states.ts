import { IconName } from './icon';

/**
 * Catálogo único de estados visuales del panel (VIG-33). Ninguna página define colores de
 * estado por su cuenta: los toma de aquí.
 *
 * Cada estado se comunica con texto e ícono, nunca solo con color (WCAG 1.4.1). Los colores
 * van en hex y no como clases de Tailwind para que un test pueda medir su contraste:
 * - `foreground` sobre `background`: ≥ 4.5:1 (texto de la etiqueta e ícono);
 * - `map` sobre blanco: ≥ 3:1 (trazos y marcadores sobre el mapa).
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
/** Invertido: lo único que debe saltar a la vista aunque haya rojo alrededor. */
const ALARM = { foreground: '#ffffff', background: '#991b1b', map: '#7f1d1d' };

export type IncidentState = 'open' | 'acknowledged' | 'resolved' | 'exhausted';
export type Severity = 'info' | 'warning' | 'critical';
export type RiskLevelKey = 'low' | 'medium' | 'high' | 'critical';
export type StationState = 'reporting' | 'silent' | 'unzoned' | 'inactive';

/** `exhausted`: abierto y sin nadie que confirme en ningún nivel (SPEC: "en rojo"). */
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

/** Las barras del ícono suben con el nivel: el orden se lee también sin color. */
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
};

export const ALL_CATALOGS = {
  incident: INCIDENT_STATES,
  severity: SEVERITIES,
  risk: RISK_LEVEL_STATES,
  station: STATION_STATES,
} as const;
