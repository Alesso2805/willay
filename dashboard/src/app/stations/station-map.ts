import {
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  effect,
  inject,
  input,
  output,
  viewChild,
} from '@angular/core';
import * as L from 'leaflet';
import { t } from '../i18n/i18n';
import { createBaseMap, plainText } from '../map/base-map';
import { Zone } from '../zones/zones.api';
import { Station } from './stations.api';

export type LonLat = [number, number];

/**
 * Station map. A "dumb" component: it receives stations, context zones and whether a location
 * is being picked, and emits the clicked point. Saving is the page's job.
 */
@Component({
  selector: 'app-station-map',
  template: `<div
    #container
    class="h-[24rem] w-full lg:h-[calc(100vh-11rem)] lg:min-h-[28rem]"
    [class.cursor-crosshair]="picking()"
    role="region"
    [attr.aria-label]="t('stations.mapLabel')"
  ></div>`,
})
export class StationMap {
  readonly stations = input<Station[]>([]);
  readonly zones = input<Zone[]>([]);
  readonly picking = input(false);
  readonly pending = input<LonLat | null>(null);
  readonly selectedId = input<string | null>(null);
  readonly picked = output<LonLat>();

  protected readonly t = t;
  private readonly container = viewChild.required<ElementRef<HTMLDivElement>>('container');
  private map?: L.Map;
  private readonly zoneLayer = L.featureGroup();
  private readonly stationLayer = L.featureGroup();
  private pendingMarker?: L.CircleMarker;
  private fitted = false;

  constructor() {
    afterNextRender(() => this.init());
    effect(() => this.renderZones(this.zones()));
    effect(() => this.renderStations(this.stations(), this.selectedId()));
    effect(() => this.showPending(this.pending()));
    inject(DestroyRef).onDestroy(() => this.map?.remove());
  }

  private init(): void {
    const map = createBaseMap(this.container().nativeElement);
    this.zoneLayer.addTo(map);
    this.stationLayer.addTo(map);
    map.on('click', (event: L.LeafletMouseEvent) => {
      if (this.picking()) this.picked.emit([event.latlng.lng, event.latlng.lat]);
    });
    this.map = map;
    this.renderZones(this.zones());
    this.renderStations(this.stations(), this.selectedId());
    this.showPending(this.pending());
  }

  private renderZones(zones: Zone[]): void {
    if (!this.map) return;
    this.zoneLayer.clearLayers();
    for (const zone of zones) {
      // interactive: false → the click goes through the zone to the map (location picking).
      L.geoJSON(zone.geometry, {
        interactive: false,
        style: { color: '#64748b', weight: 1, dashArray: '3 4', fillOpacity: 0.05 },
      }).addTo(this.zoneLayer);
    }
  }

  private renderStations(stations: Station[], selectedId: string | null): void {
    if (!this.map) return;
    this.stationLayer.clearLayers();
    for (const station of stations) {
      const [lon, lat] = station.location.coordinates;
      const active = station.status === 'active';
      const marker = L.circleMarker([lat, lon], {
        radius: station.id === selectedId ? 11 : 8,
        color: !active ? '#64748b' : station.has_zone ? '#1d4ed8' : '#a16207',
        weight: station.id === selectedId ? 4 : 2,
        // No zone: dashed border as well as color (state is never conveyed by color alone).
        dashArray: station.has_zone ? undefined : '3 3',
        fillOpacity: active ? 0.6 : 0.2,
      });
      const value = station.heartbeat?.last_value;
      const reading = value === null || value === undefined ? '' : ` · ${value} ${station.unit}`;
      const noZone = station.has_zone ? '' : ` · ${t('stations.tooltipNoZone')}`;
      marker.bindTooltip(plainText(`${station.code} · ${station.name}${reading}${noZone}`));
      this.stationLayer.addLayer(marker);
    }
    if (!this.fitted && stations.length > 0) {
      this.map.fitBounds(this.stationLayer.getBounds(), { padding: [32, 32], maxZoom: 13 });
      this.fitted = true;
    }
  }

  private showPending(point: LonLat | null): void {
    if (!this.map) return;
    this.pendingMarker?.remove();
    this.pendingMarker = undefined;
    if (point) {
      const [lon, lat] = point;
      this.pendingMarker = L.circleMarker([lat, lon], { radius: 10, color: '#15803d', weight: 3 })
        .bindTooltip(t('stations.newLocation'), { permanent: true, direction: 'top' })
        .addTo(this.map);
    }
  }
}
