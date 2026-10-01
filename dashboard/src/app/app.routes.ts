import { Routes } from '@angular/router';
import { HomePage } from './home-page';

export const routes: Routes = [
  { path: '', component: HomePage, title: 'Willay' },
  {
    path: 'zonas',
    title: 'Zonas de riesgo · Willay',
    // Lazy loaded: Leaflet and Geoman are only downloaded when the map is opened.
    loadComponent: () => import('./zones/zones-page').then((m) => m.ZonesPage),
  },
  {
    path: 'estaciones',
    title: 'Estaciones · Willay',
    loadComponent: () => import('./stations/stations-page').then((m) => m.StationsPage),
  },
  { path: '**', redirectTo: '' },
];
