// Order matters: Leaflet defines window.L and Geoman hooks into that global.
import * as L from 'leaflet';
import '@geoman-io/leaflet-geoman-free';

export const RIMAC_CENTER: L.LatLngExpression = [-11.95, -76.72];

/**
 * Tooltip content that is only text. Leaflet inserts a string tooltip as HTML, so a zone or
 * station named "<img onerror=…>" would run in the browser of whoever hovers over it; an element
 * whose textContent holds the name is never parsed.
 */
export function plainText(text: string): HTMLElement {
  const element = document.createElement('span');
  element.textContent = text;
  return element;
}

/** Shared base map: OpenStreetMap tiles centered on the Rímac basin. */
export function createBaseMap(container: HTMLElement): L.Map {
  const map = L.map(container).setView(RIMAC_CENTER, 11);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; colaboradores de OpenStreetMap',
  }).addTo(map);
  return map;
}
