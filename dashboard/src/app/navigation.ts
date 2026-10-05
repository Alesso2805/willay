import { TranslationKey } from './i18n/i18n';
import { IconName } from './ui/icon';

/**
 * Dashboard sections and the permission each one requires (SPEC, "Permissions by role"). Hiding
 * a section is only a convenience: the API checks the permission on every endpoint anyway.
 */
export interface NavItem {
  path: string;
  label: TranslationKey;
  icon: IconName;
  /** null: anyone signed in. Home explains what to do to users without roles. */
  permission: string | null;
  exact: boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { path: '/', label: 'nav.home', icon: 'home', permission: null, exact: true },
  { path: '/mapa', label: 'nav.map', icon: 'radar', permission: 'view', exact: false },
  { path: '/incidentes', label: 'nav.incidents', icon: 'bell', permission: 'view', exact: false },
  { path: '/zonas', label: 'nav.zones', icon: 'map', permission: 'view', exact: false },
  { path: '/estaciones', label: 'nav.stations', icon: 'antenna', permission: 'view', exact: false },
  { path: '/reglas', label: 'nav.rules', icon: 'sliders', permission: 'view', exact: false },
  {
    path: '/contactos',
    label: 'nav.contacts',
    icon: 'users',
    permission: 'contacts:view_details',
    exact: false,
  },
  {
    path: '/organizacion',
    label: 'nav.organization',
    icon: 'building',
    permission: 'organization:manage',
    exact: false,
  },
  {
    path: '/auditoria',
    label: 'nav.audit',
    icon: 'history',
    permission: 'audit:view',
    exact: false,
  },
];

export function visibleNavItems(permissions: readonly string[]): NavItem[] {
  return NAV_ITEMS.filter(
    (item) => item.permission === null || permissions.includes(item.permission),
  );
}
