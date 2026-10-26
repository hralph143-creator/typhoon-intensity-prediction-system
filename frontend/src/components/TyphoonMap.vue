<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { Observation } from '@/types/typhoon'
import { numberText, unwrapTrack, utc, windColor } from '@/utils/typhoon'

const props = defineProps<{ points: Observation[]; selectedIndex: number }>()
const emit = defineEmits<{ select: [index: number] }>()
const root = ref<HTMLDivElement>()
const tileError = ref(false)
let map: L.Map | undefined
let layer: L.LayerGroup | undefined
let graticule: L.LayerGroup | undefined
let selected: L.CircleMarker | undefined
let coordinates: [number, number][] = []
let observer: ResizeObserver | undefined

function longitudeLabel(longitude: number) {
  const normalized = ((longitude + 180) % 360 + 360) % 360 - 180
  return `${Math.abs(normalized)}°${normalized < 0 ? 'W' : 'E'}`
}
function renderGraticule() {
  if (!map) return
  graticule?.remove()
  graticule = L.layerGroup().addTo(map)
  const bounds = map.getBounds()
  const south = Math.max(-80, bounds.getSouth()), north = Math.min(80, bounds.getNorth())
  const west = bounds.getWest(), east = bounds.getEast()
  const style = { color: '#8aa1b6', weight: 1, opacity: .48, dashArray: '3 5', interactive: false, pane: 'graticule' }
  function label(location: [number, number], text: string) {
    L.marker(location, { interactive: false, pane: 'graticule', icon: L.divIcon({ className: 'grid-coordinate', html: text, iconSize: [50, 18], iconAnchor: [0, 0] }) }).addTo(graticule!)
  }
  for (let latitude = Math.ceil(south / 10) * 10; latitude <= north; latitude += 10) {
    L.polyline([[latitude, west], [latitude, east]], style).addTo(graticule)
    label([latitude, west + (east - west) * .02], `${Math.abs(latitude)}°${latitude < 0 ? 'S' : 'N'}`)
  }
  for (let longitude = Math.ceil(west / 10) * 10; longitude <= east; longitude += 10) {
    L.polyline([[south, longitude], [north, longitude]], style).addTo(graticule)
    label([north - (north - south) * .03, longitude], longitudeLabel(longitude))
  }
}

function selection() {
  selected?.remove()
  const location = coordinates[props.selectedIndex]
  if (map && location) selected = L.circleMarker(location, { radius: 9, color: '#173c65', weight: 3, fillColor: '#fff', fillOpacity: .55 }).addTo(map)
}
function render() {
  if (!map) return
  layer?.remove()
  layer = L.layerGroup().addTo(map)
  coordinates = unwrapTrack(props.points)
  if (!coordinates.length) return
  L.polyline(coordinates, { color: '#476b8e', weight: 2, opacity: .8 }).addTo(layer)
  props.points.forEach((point, index) => {
    const marker = L.circleMarker(coordinates[index], {
      radius: 4.5, color: '#fff', weight: 1,
      fillColor: windColor(point.cma_wind_ms), fillOpacity: 1,
    }).addTo(layer!)
    const tooltip = document.createElement('div')
    tooltip.textContent = `${utc(point.observation_time)} · CMA ${numberText(point.cma_wind_ms)} m/s · ${numberText(point.cma_pressure, 0)} hPa`
    marker.bindTooltip(tooltip)
    marker.on('mouseover click', () => emit('select', index))
  })
  for (const [index, text] of [[0, '起点'], [coordinates.length - 1, '终点']] as const) {
    L.marker(coordinates[index], { icon: L.divIcon({ className: 'track-endpoint', html: `<span>${text}</span>`, iconSize: [40, 24], iconAnchor: [20, 30] }) }).addTo(layer)
  }
  map.fitBounds(L.latLngBounds(coordinates), { padding: [38, 38], maxZoom: 6, animate: false })
  renderGraticule()
  selection()
}
onMounted(() => {
  map = L.map(root.value!, { worldCopyJump: false }).setView([22, 135], 3)
  map.createPane('graticule').style.zIndex = '350'
  map.on('moveend zoomend', renderGraticule)
  const tiles = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
    maxZoom: 10,
  }).addTo(map)
  tiles.on('tileerror', () => { tileError.value = true })
  observer = new ResizeObserver(() => map?.invalidateSize())
  observer.observe(root.value!)
  render()
})
watch(() => props.points, render)
watch(() => props.selectedIndex, selection)
onBeforeUnmount(() => {
  observer?.disconnect()
  map?.stop()
  map?.off()
  layer?.clearLayers()
  graticule?.clearLayers()
  selected?.remove()
  map?.remove()
  map = undefined
})
</script>

<template>
  <div class="map-wrap">
    <div ref="root" class="track-map" aria-label="真实台风历史路径地图" />
    <div class="grid-note">经纬网 · 10°</div>
    <div v-if="tileError" class="tile-note">底图不可用，显示经纬网和真实轨迹。</div>
  </div>
</template>

<style>
.map-wrap { position: relative; }
.track-map { height: 420px; background: #e8eff5; border: 1px solid #dfe5ec; border-radius: 3px; z-index: 1; }
.tile-note { position: absolute; bottom: 26px; left: 12px; z-index: 500; background: #fff; padding: 7px 10px; color: #7c5e24; font-size: 12px; }
.track-endpoint span { padding: 3px 6px; background: #244b71; color: #fff; white-space: nowrap; font-size: 11px; border-radius: 3px; }
.grid-coordinate { color: #627f99; font-size: 10px; white-space: nowrap; text-shadow: 0 1px 2px #fff; pointer-events: none; }
.grid-note { position: absolute; top: 10px; right: 10px; z-index: 500; padding: 4px 7px; color: #6f879d; font-size: 10px; background: #ffffffe6; }
</style>
