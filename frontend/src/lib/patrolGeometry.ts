/** Pure helpers for patrol-task coordinates (inspection areas and planned paths). */

export interface LatLngPoint {
  lat: number
  lng: number
}

export const MAP_PICK_POINT_LIMIT = 4

export function normalizePointList(rawPoints: unknown, maxPoints = MAP_PICK_POINT_LIMIT): LatLngPoint[] {
  if (!Array.isArray(rawPoints)) return []
  return rawPoints
    .map((point) => ({ lat: Number(point?.lat), lng: Number(point?.lng) }))
    .filter((point) => Number.isFinite(point.lat) && Number.isFinite(point.lng))
    .filter((point) => point.lat >= -90 && point.lat <= 90 && point.lng >= -180 && point.lng <= 180)
    .slice(0, maxPoints)
}

/** Parse "lat,lng" lines. Throws an Error with a user-facing message on invalid input. */
export function parseCoordinateLines(rawText: string, fieldLabel: string, minimumPoints = 0, allowEmpty = false): LatLngPoint[] {
  const lines = String(rawText || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)

  if (!lines.length) {
    if (allowEmpty) return []
    throw new Error(`${fieldLabel} 不能为空`)
  }

  const points = lines.map((line, index) => {
    const parts = line.split(/[，,\s]+/).filter(Boolean)
    if (parts.length < 2) {
      throw new Error(`${fieldLabel} 第 ${index + 1} 行格式错误，应为 lat,lng`)
    }
    const lat = Number(parts[0])
    const lng = Number(parts[1])
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
      throw new Error(`${fieldLabel} 第 ${index + 1} 行包含非法坐标`)
    }
    if (lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      throw new Error(`${fieldLabel} 第 ${index + 1} 行坐标越界`)
    }
    return { lat, lng }
  })

  if (points.length < minimumPoints) {
    throw new Error(`${fieldLabel} 至少需要 ${minimumPoints} 个点`)
  }
  return points
}

/** Parse and validate the area (exactly 4 points) and path (empty or exactly 4 points) text fields. */
export function parseTaskGeometry(areaText: string, pathText: string) {
  const area = parseCoordinateLines(areaText, '巡检区域', 3, false)
  const path = parseCoordinateLines(pathText, '规划路径', 2, true)
  if (area.length !== MAP_PICK_POINT_LIMIT) throw new Error(`巡检区域必须是 ${MAP_PICK_POINT_LIMIT} 个点`)
  if (path.length !== 0 && path.length !== MAP_PICK_POINT_LIMIT) throw new Error(`规划路径为空或必须是 ${MAP_PICK_POINT_LIMIT} 个点`)
  return { area, path }
}

export function formatCoordinateLines(points: LatLngPoint[]): string {
  if (!Array.isArray(points) || !points.length) return ''
  return points.map((point) => `${Number(point.lat).toFixed(6)},${Number(point.lng).toFixed(6)}`).join('\n')
}

function orientation(a: LatLngPoint, b: LatLngPoint, c: LatLngPoint) {
  const value = (b.lng - a.lng) * (c.lat - a.lat) - (b.lat - a.lat) * (c.lng - a.lng)
  if (Math.abs(value) < 1e-12) return 0
  return value > 0 ? 1 : -1
}

function onSegment(a: LatLngPoint, b: LatLngPoint, p: LatLngPoint) {
  return (
    p.lng <= Math.max(a.lng, b.lng) + 1e-12 &&
    p.lng + 1e-12 >= Math.min(a.lng, b.lng) &&
    p.lat <= Math.max(a.lat, b.lat) + 1e-12 &&
    p.lat + 1e-12 >= Math.min(a.lat, b.lat)
  )
}

function segmentsIntersect(a: LatLngPoint, b: LatLngPoint, c: LatLngPoint, d: LatLngPoint) {
  const o1 = orientation(a, b, c)
  const o2 = orientation(a, b, d)
  const o3 = orientation(c, d, a)
  const o4 = orientation(c, d, b)

  if (o1 !== o2 && o3 !== o4) return true
  if (o1 === 0 && onSegment(a, b, c)) return true
  if (o2 === 0 && onSegment(a, b, d)) return true
  if (o3 === 0 && onSegment(c, d, a)) return true
  if (o4 === 0 && onSegment(c, d, b)) return true
  return false
}

function pointInPolygon(point: LatLngPoint, polygon: LatLngPoint[]) {
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const xi = polygon[i].lng
    const yi = polygon[i].lat
    const xj = polygon[j].lng
    const yj = polygon[j].lat
    const intersects = ((yi > point.lat) !== (yj > point.lat)) &&
      (point.lng < ((xj - xi) * (point.lat - yi)) / ((yj - yi) || 1e-12) + xi)
    if (intersects) inside = !inside
  }
  return inside
}

export function polygonsOverlap(polyA: LatLngPoint[], polyB: LatLngPoint[]) {
  if (polyA.length < 3 || polyB.length < 3) return false

  for (let i = 0; i < polyA.length; i += 1) {
    const a1 = polyA[i]
    const a2 = polyA[(i + 1) % polyA.length]
    for (let j = 0; j < polyB.length; j += 1) {
      const b1 = polyB[j]
      const b2 = polyB[(j + 1) % polyB.length]
      if (segmentsIntersect(a1, a2, b1, b2)) return true
    }
  }
  return pointInPolygon(polyA[0], polyB) || pointInPolygon(polyB[0], polyA)
}
