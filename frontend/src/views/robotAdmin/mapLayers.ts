/** Leaflet drawing helpers for the robot admin map. */
import L from 'leaflet'
import { normalizePointList, type LatLngPoint } from '../../lib/patrolGeometry'
import type { PatrolTask } from './shared'

const MARKER_ANIMATION_MS = 420

type LatLngTuple = [number, number]
const toLatLng = (point: LatLngPoint): LatLngTuple => [point.lat, point.lng]

/** Animation frame ids of markers that are currently moving, keyed by marker. */
export type MarkerFrames = Map<L.Marker, number>

export function stopMarkerAnimation(marker: L.Marker, frames: MarkerFrames) {
  const frame = frames.get(marker)
  if (frame) {
    window.cancelAnimationFrame(frame)
    frames.delete(marker)
  }
}

/** Glide a marker to its new position instead of jumping there. */
export function animateMarkerTo(marker: L.Marker, nextLat: number, nextLng: number, frames: MarkerFrames) {
  const current = marker.getLatLng()
  const startLat = Number(current?.lat)
  const startLng = Number(current?.lng)
  const endLat = Number(nextLat)
  const endLng = Number(nextLng)

  if (![startLat, startLng, endLat, endLng].every(Number.isFinite)) {
    marker.setLatLng([nextLat, nextLng])
    return
  }
  const deltaLat = endLat - startLat
  const deltaLng = endLng - startLng
  if (Math.abs(deltaLat) + Math.abs(deltaLng) < 1e-10) {
    marker.setLatLng([endLat, endLng])
    return
  }

  stopMarkerAnimation(marker, frames)
  const startedAt = performance.now()
  const step = (now: number) => {
    const t = Math.min((now - startedAt) / MARKER_ANIMATION_MS, 1)
    const eased = t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2
    marker.setLatLng([startLat + deltaLat * eased, startLng + deltaLng * eased])
    if (t < 1) {
      frames.set(marker, window.requestAnimationFrame(step))
    } else {
      frames.delete(marker)
    }
  }
  frames.set(marker, window.requestAnimationFrame(step))
}

/** Draw the task being edited: draft points, the area polygon and the path line. */
export function drawDraftTask(layer: L.LayerGroup, areaPoints: LatLngPoint[], pathPoints: LatLngPoint[]) {
  layer.clearLayers()

  areaPoints.forEach((point) => {
    L.circleMarker(toLatLng(point), { radius: 5, color: '#d53f50', weight: 2, fillColor: '#ef7483', fillOpacity: 0.85 }).addTo(layer)
  })
  const areaLatLngs = areaPoints.map(toLatLng)
  if (areaPoints.length >= 3) {
    L.polygon(areaLatLngs, { color: '#d53f50', weight: 2, fillColor: '#ef7483', fillOpacity: 0.18 }).addTo(layer)
  } else if (areaPoints.length >= 2) {
    L.polyline(areaLatLngs, { color: '#d53f50', weight: 2 }).addTo(layer)
  }

  pathPoints.forEach((point) => {
    L.circleMarker(toLatLng(point), { radius: 5, color: '#2563eb', weight: 2, fillColor: '#60a5fa', fillOpacity: 0.85 }).addTo(layer)
  })
  if (pathPoints.length >= 2) {
    L.polyline(pathPoints.map(toLatLng), { color: '#2563eb', weight: 3, dashArray: '6 6' }).addTo(layer)
  }
}

/** Draw the saved patrol tasks of the selected robot; running tasks use warmer colors. */
export function drawPatrolTasks(layer: L.LayerGroup, tasks: PatrolTask[]) {
  layer.clearLayers()

  tasks.forEach((task) => {
    const areaPoints = normalizePointList(task.inspection_area || [])
    const pathPoints = normalizePointList(task.planned_path || [])
    const isRunning = String(task.status || '').toUpperCase() === 'RUNNING'
    const areaColor = isRunning ? '#f97316' : '#d53f50'
    const areaFillColor = isRunning ? '#fdba74' : '#ef7483'
    const pathColor = isRunning ? '#0f766e' : '#2563eb'
    const label = task.name || `任务 #${task.id}`

    areaPoints.forEach((point) => {
      L.circleMarker(toLatLng(point), { radius: 4, color: areaColor, weight: 1.5, fillColor: areaFillColor, fillOpacity: 0.72 })
        .bindTooltip(label).addTo(layer)
    })
    if (areaPoints.length >= 3) {
      L.polygon(areaPoints.map(toLatLng), {
        color: areaColor, weight: 2, fillColor: areaFillColor, fillOpacity: 0.14,
      }).bindTooltip(`${label} 检测区`).addTo(layer)
    }

    pathPoints.forEach((point) => {
      L.circleMarker(toLatLng(point), { radius: 4, color: pathColor, weight: 1.5, fillColor: '#60a5fa', fillOpacity: 0.72 })
        .bindTooltip(label).addTo(layer)
    })
    if (pathPoints.length >= 2) {
      L.polyline(pathPoints.map(toLatLng), {
        color: pathColor, weight: 2.5, dashArray: '6 6', opacity: 0.88,
      }).bindTooltip(`${label} 路径`).addTo(layer)
    }
  })
}
