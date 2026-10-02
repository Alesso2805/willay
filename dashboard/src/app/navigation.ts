import { IconName } from './ui/icon';

/**
 * Dashboard sections and the permission each one requires (SPEC, "Permissions by role"). Hiding
 * a section is only a convenience: the API checks the permission on every endpoint anyway.
 */
export interface NavItem {
  path: string;
  label: string;
  icon: IconName;
  /** null: anyone signed in. Home explains what to do to users without roles. */
  permission: string | null;
  exact: boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { path: '/', label: 'Inicio', icon: 'home', permission: null, exact: true },
  { path: '/mapa', label: 'Mapa en vivo', icon: 'radar', permission: 'view', exact: false },
  { path: '/zonas', label: 'Zonas', icon: 'map', permission: 'view', exact: false },
  { path: '/estaciones', label: 'Estaciones', icon: 'antenna', permission: 'view', exact: false },
];

export function visibleNavItems(permissions: readonly string[]): NavItem[] {
  return NAV_ITEMS.filter(
    (item) => item.permission === null || permissions.includes(item.permission),
  );
}
