import type { Map as LeafletMap } from 'leaflet'

export interface MapPoint {
  lat: unknown
  lng: unknown
  weight?: unknown
}

interface NormalizedPoint {
  lat: number
  lng: number
  weight: number
}

interface FocusOptions {
  gridSize?: number
  maxZoom?: number
  singlePointZoom?: number
}

function toFiniteNumber(value: unknown): number | null {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizePoints(points: MapPoint[]): NormalizedPoint[] {
  return (Array.isArray(points) ? points : [])
    .map((item) => {
      const lat = toFiniteNumber(item?.lat)
      const lng = toFiniteNumber(item?.lng)
      if (lat == null || lng == null) return null
      const weight = Math.max(1, toFiniteNumber(item?.weight) || 1)
      return { lat, lng, weight }
    })
    .filter((item): item is NormalizedPoint => item !== null)
}

function pickDenseCluster(points: NormalizedPoint[], gridSize: number): NormalizedPoint[] {
  const buckets = new Map<string, { points: NormalizedPoint[]; weight: number }>()

  points.forEach((point) => {
    const key = `${Math.floor(point.lat / gridSize)}:${Math.floor(point.lng / gridSize)}`
    let bucket = buckets.get(key)
    if (!bucket) {
      bucket = { points: [], weight: 0 }
      buckets.set(key, bucket)
    }
    bucket.points.push(point)
    bucket.weight += point.weight
  })

  let best: { points: NormalizedPoint[]; weight: number } | null = null
  buckets.forEach((bucket) => {
    if (
      !best ||
      bucket.weight > best.weight ||
      (bucket.weight === best.weight && bucket.points.length > best.points.length)
    ) {
      best = bucket
    }
  })

  return (best as { points: NormalizedPoint[] } | null)?.points || []
}

/** Zoom the map to the densest cluster of points. Returns true if the map was moved. */
export function focusMapToDenseRegion(map: LeafletMap | null, points: MapPoint[], options: FocusOptions = {}): boolean {
  if (!map) return false

  const normalized = normalizePoints(points)
  if (!normalized.length) return false

  const gridSize = Number.isFinite(Number(options.gridSize)) ? Number(options.gridSize) : 0.35
  const maxZoom = Number.isFinite(Number(options.maxZoom)) ? Number(options.maxZoom) : 14
  const singlePointZoom = Number.isFinite(Number(options.singlePointZoom)) ? Number(options.singlePointZoom) : 14

  const densePoints = pickDenseCluster(normalized, Math.max(0.05, gridSize))
  const targetPoints = densePoints.length ? densePoints : normalized

  const uniqueKeys = new Set(targetPoints.map((point) => `${point.lat.toFixed(6)}:${point.lng.toFixed(6)}`))
  if (uniqueKeys.size === 1) {
    const point = targetPoints[0]
    map.setView([point.lat, point.lng], singlePointZoom, { animate: false })
    return true
  }

  map.fitBounds(
    targetPoints.map((point) => [point.lat, point.lng] as [number, number]),
    { maxZoom, padding: [36, 36], animate: false },
  )
  return true
}
