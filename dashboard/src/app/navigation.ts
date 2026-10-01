import { IconName } from './ui/icon';

/**
 * Secciones del panel y el permiso que pide cada una (SPEC, "Permisos por rol"). Ocultar
 * una sección es solo comodidad: la API valida el permiso en cada endpoint igual.
 */
export interface NavItem {
  path: string;
  label: string;
  icon: IconName;
  /** null: cualquiera con sesión. Inicio explica qué hacer a quien no tiene roles. */
  permission: string | null;
  exact: boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { path: '/', label: 'Inicio', icon: 'home', permission: null, exact: true },
  { path: '/zonas', label: 'Zonas', icon: 'map', permission: 'view', exact: false },
  { path: '/estaciones', label: 'Estaciones', icon: 'antenna', permission: 'view', exact: false },
];

export function visibleNavItems(permissions: readonly string[]): NavItem[] {
  return NAV_ITEMS.filter(
    (item) => item.permission === null || permissions.includes(item.permission),
  );
}
