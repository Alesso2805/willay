import { Routes } from '@angular/router';
import { HomePage } from './home-page';

export const routes: Routes = [
  { path: '', component: HomePage, title: 'Vigía' },
  {
    path: 'zonas',
    title: 'Zonas de riesgo · Vigía',
    // Carga diferida: Leaflet y Geoman solo se descargan al abrir el mapa.
    loadComponent: () => import('./zones/zones-page').then((m) => m.ZonesPage),
  },
  { path: '**', redirectTo: '' },
];
