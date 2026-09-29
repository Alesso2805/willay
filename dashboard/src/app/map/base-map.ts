// Orden importante: Leaflet define window.L y Geoman se engancha a ese global.
import * as L from 'leaflet';
import '@geoman-io/leaflet-geoman-free';

export const RIMAC_CENTER: L.LatLngExpression = [-11.95, -76.72];

/** Mapa base común: teselas de OpenStreetMap centradas en la cuenca del Rímac. */
export function createBaseMap(container: HTMLElement): L.Map {
  const map = L.map(container).setView(RIMAC_CENTER, 11);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; colaboradores de OpenStreetMap',
  }).addTo(map);
  return map;
}
