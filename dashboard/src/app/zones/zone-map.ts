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
import { createBaseMap, plainText } from '../map/base-map';
import { RISK_STYLES, riskLabel } from './zone-presentation';
import { MultiPolygonGeometry, PolygonGeometry, Position, Zone } from './zones.api';

export type MapMode = { kind: 'view' } | { kind: 'draw' } | { kind: 'edit'; zoneId: string };
export type DrawnGeometry = PolygonGeometry | MultiPolygonGeometry;

// Geoman does not let a self-intersecting polygon be closed or edited. The server validates
// it with PostGIS anyway: the map helps, the API decides.
const NO_SELF_INTERSECTION = { allowSelfIntersection: false } as const;

/**
 * Zone map with Leaflet + Leaflet-Geoman. A "dumb" component: it receives zones and the mode,
 * and emits the drawn or edited geometry. Saving and showing errors is the page's job.
 */
@Component({
  selector: 'app-zone-map',
  template: `<div
    #container
    class="h-[24rem] w-full lg:h-[calc(100vh-11rem)] lg:min-h-[28rem]"
    role="region"
    aria-label="Mapa de zonas de riesgo. La lista junto al mapa muestra la misma información."
  ></div>`,
})
export class ZoneMap {
  readonly zones = input<Zone[]>([]);
  readonly mode = input<MapMode>({ kind: 'view' });
  readonly problem = input<Position | null>(null);
  /** Geometry of the new or edited polygon, every time the operator changes it. */
  readonly geometryChange = output<DrawnGeometry>();

  private readonly container = viewChild.required<ElementRef<HTMLDivElement>>('container');
  private map?: L.Map;
  private readonly zoneLayer = L.featureGroup();
  private readonly layersById = new Map<string, L.Polygon>();
  private draft?: L.Polygon;
  private problemMarker?: L.CircleMarker;
  private fitted = false;

  constructor() {
    afterNextRender(() => this.init());
    // Each effect reads its signal before checking whether the map exists, so it stays
    // subscribed and runs again when the zones or the mode change.
    effect(() => this.renderZones(this.zones()));
    effect(() => this.applyMode(this.mode()));
    effect(() => this.showProblem(this.problem()));
    inject(DestroyRef).onDestroy(() => this.map?.remove());
  }

  private init(): void {
    const map = createBaseMap(this.container().nativeElement);
    this.zoneLayer.addTo(map);
    map.on('pm:create', (event) => {
      this.draft = event.layer as L.Polygon;
      map.pm.disableDraw();
      this.draft.pm.enable(NO_SELF_INTERSECTION); // the draft stays editable
      this.draft.on('pm:edit', () => this.emit(this.draft));
      this.emit(this.draft);
    });
    this.map = map;
    this.renderZones(this.zones());
    this.applyMode(this.mode());
    this.showProblem(this.problem());
  }

  private renderZones(zones: Zone[]): void {
    if (!this.map) return;
    this.zoneLayer.clearLayers();
    this.layersById.clear();
    for (const zone of zones) {
      const style = zone.is_active
        ? RISK_STYLES[zone.risk_level]
        : { color: '#64748b', dashArray: '4 4', weight: 1 };
      const layer = L.geoJSON(zone.geometry, { style: { ...style, fillOpacity: 0.15 } })
        .getLayers()[0] as L.Polygon;
      const state = zone.is_active ? '' : ' (desactivada)';
      layer.bindTooltip(plainText(`${zone.name} · riesgo ${riskLabel(zone.risk_level)}${state}`), {
        sticky: true,
      });
      this.zoneLayer.addLayer(layer);
      this.layersById.set(zone.id, layer);
    }
    if (!this.fitted && zones.length > 0) {
      this.map.fitBounds(this.zoneLayer.getBounds(), { padding: [24, 24] });
      this.fitted = true;
    }
  }

  private applyMode(mode: MapMode): void {
    if (!this.map) return;
    this.map.pm.disableDraw();
    this.layersById.forEach((layer) => layer.pm.disable());
    if (mode.kind !== 'draw' && this.draft) {
      this.draft.remove();
      this.draft = undefined;
    }
    if (mode.kind === 'draw' && !this.draft) {
      this.map.pm.enableDraw('Polygon', NO_SELF_INTERSECTION);
    }
    if (mode.kind === 'edit') {
      const layer = this.layersById.get(mode.zoneId);
      if (!layer) return;
      layer.pm.enable(NO_SELF_INTERSECTION);
      layer.off('pm:edit').on('pm:edit', () => this.emit(layer));
      this.map.fitBounds(layer.getBounds(), { padding: [24, 24] });
    }
  }

  private showProblem(point: Position | null): void {
    if (!this.map) return;
    this.problemMarker?.remove();
    this.problemMarker = undefined;
    if (point) {
      const [lon, lat] = point; // GeoJSON is [lon, lat]; Leaflet uses [lat, lon]
      this.problemMarker = L.circleMarker([lat, lon], {
        radius: 9,
        color: '#b91c1c',
        weight: 3,
        fillOpacity: 0.4,
      })
        .bindTooltip('Aquí se cruza el polígono', { permanent: true, direction: 'top' })
        .addTo(this.map);
    }
  }

  private emit(layer: L.Polygon | undefined): void {
    if (layer) this.geometryChange.emit(layer.toGeoJSON().geometry as DrawnGeometry);
  }
}
