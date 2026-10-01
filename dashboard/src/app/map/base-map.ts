// Order matters: Leaflet defines window.L and Geoman hooks into that global.
import * as L from 'leaflet';
import '@geoman-io/leaflet-geoman-free';

export const RIMAC_CENTER: L.LatLngExpression = [-11.95, -76.72];

/** Shared base map: OpenStreetMap tiles centered on the Rímac basin. */
export function createBaseMap(container: HTMLElement): L.Map {
  const map = L.map(container).setView(RIMAC_CENTER, 11);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; colaboradores de OpenStreetMap',
  }).addTo(map);
  return map;
}
