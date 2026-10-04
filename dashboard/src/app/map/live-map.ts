import {
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  effect,
  inject,
  input,
  viewChild,
} from '@angular/core';
import * as L from 'leaflet';
import { ZONE_STATES } from '../ui/visual-states';
import { riskLabel } from '../zones/zone-presentation';
import { createBaseMap } from './base-map';
import { StationView, ZONE_STYLES, ZoneView, markerHtml } from './live-map-presentation';

/**
 * The live map (VIG-25). A "dumb" component: it draws the zones by state and the stations by
 * their marker state; the page computes both. The station markers are kept and updated in
 * place, because their tooltips change every second (the age of the last value).
 */
@Component({
  selector: 'app-live-map',
  template: `<div
    #container
    class="h-[24rem] w-full lg:h-[calc(100vh-14rem)] lg:min-h-[28rem]"
    role="region"
    aria-label="Mapa en vivo de zonas y estaciones. Las listas junto al mapa muestran la misma información."
  ></div>`,
})
export class LiveMap {
  readonly zones = input<ZoneView[]>([]);
  readonly stations = input<StationView[]>([]);

  private readonly container = viewChild.required<ElementRef<HTMLDivElement>>('container');
  private map?: L.Map;
  private readonly zoneLayer = L.featureGroup();
  private readonly stationLayer = L.featureGroup();
  /** By station id, with the HTML it shows, to replace the icon only when it changes. */
  private readonly markers = new Map<string, { marker: L.Marker; html: string }>();
  private drawnZones?: ZoneView[];
  private fitted = false;

  constructor() {
    afterNextRender(() => this.init());
    effect(() => this.render(this.zones(), this.stations()));
    inject(DestroyRef).onDestroy(() => this.map?.remove());
  }

  private init(): void {
    const map = createBaseMap(this.container().nativeElement);
    this.zoneLayer.addTo(map);
    this.stationLayer.addTo(map);
    this.map = map;
    this.render(this.zones(), this.stations());
  }

  private render(zones: ZoneView[], stations: StationView[]): void {
    if (!this.map) return;
    // The page recomputes the zones only when an incident or a zone changes, not every second.
    if (zones !== this.drawnZones) {
      this.drawZones(zones);
      this.drawnZones = zones;
    }
    this.drawStations(stations);
    if (!this.fitted) this.fit();
  }

  private drawZones(views: ZoneView[]): void {
    this.zoneLayer.clearLayers();
    for (const { zone, state, summary } of views) {
      const risk = riskLabel(zone.risk_level).toLowerCase();
      L.geoJSON(zone.geometry, { style: { color: ZONE_STATES[state].map, ...ZONE_STYLES[state] } })
        .bindTooltip(`${zone.name} · ${summary} · riesgo ${risk}`, { sticky: true })
        .addTo(this.zoneLayer);
    }
  }

  private drawStations(views: StationView[]): void {
    const present = new Set<string>();
    for (const { station, marker: state, incident, label } of views) {
      present.add(station.id);
      const [lon, lat] = station.location.coordinates; // GeoJSON is [lon, lat]
      const html = markerHtml(state, incident);
      const known = this.markers.get(station.id);
      if (known) {
        known.marker.setLatLng([lat, lon]).setTooltipContent(label);
        if (known.html !== html) {
          known.marker.setIcon(markerIcon(html));
          known.html = html;
        }
      } else {
        // keyboard: false, the list next to the map is the keyboard and screen reader version.
        // Above and centered: a long label to one side gets clipped by the edge of the map.
        const marker = L.marker([lat, lon], { icon: markerIcon(html), keyboard: false })
          .bindTooltip(label, { direction: 'top' })
          .addTo(this.stationLayer);
        this.markers.set(station.id, { marker, html });
      }
    }
    for (const [id, { marker }] of this.markers) {
      if (!present.has(id)) {
        marker.remove();
        this.markers.delete(id);
      }
    }
  }

  /** Frames zones and stations the first time there is something to show; then the operator decides. */
  private fit(): void {
    const bounds = L.latLngBounds([]);
    for (const layer of [this.zoneLayer, this.stationLayer]) {
      const layerBounds = layer.getBounds();
      if (layerBounds.isValid()) bounds.extend(layerBounds);
    }
    if (bounds.isValid()) {
      this.map?.fitBounds(bounds, { padding: [32, 32], maxZoom: 13 });
      this.fitted = true;
    }
  }
}

function markerIcon(html: string): L.DivIcon {
  return L.divIcon({
    className: '', // no Leaflet default white square
    html,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    tooltipAnchor: [0, -14],
  });
}
