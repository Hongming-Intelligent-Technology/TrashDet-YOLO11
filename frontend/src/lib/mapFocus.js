function toFiniteNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizePoints(points) {
  return (Array.isArray(points) ? points : [])
    .map((item) => {
      const lat = toFiniteNumber(item?.lat)
      const lng = toFiniteNumber(item?.lng)
      if (lat == null || lng == null) return null
      const weight = Math.max(1, toFiniteNumber(item?.weight) || 1)
      return { lat, lng, weight }
    })
    .filter((item) => item)
}

function pickDenseCluster(points, gridSize) {
  const buckets = new Map()

  points.forEach((point) => {
    const latBucket = Math.floor(point.lat / gridSize)
    const lngBucket = Math.floor(point.lng / gridSize)
    const key = `${latBucket}:${lngBucket}`

    if (!buckets.has(key)) {
      buckets.set(key, { points: [], weight: 0 })
    }

    const bucket = buckets.get(key)
    bucket.points.push(point)
    bucket.weight += point.weight
  })

  let best = null
  buckets.forEach((bucket) => {
    if (!best) {
      best = bucket
      return
    }

    if (bucket.weight > best.weight) {
      best = bucket
      return
    }

    if (bucket.weight === best.weight && bucket.points.length > best.points.length) {
      best = bucket
    }
  })

  return best?.points || []
}

export function focusMapToDenseRegion(map, points, options = {}) {
  if (!map) return false

  const normalized = normalizePoints(points)
  if (!normalized.length) return false

  const gridSize = Number.isFinite(Number(options.gridSize)) ? Number(options.gridSize) : 0.35
  const maxZoom = Number.isFinite(Number(options.maxZoom)) ? Number(options.maxZoom) : 14
  const singlePointZoom = Number.isFinite(Number(options.singlePointZoom)) ? Number(options.singlePointZoom) : 14

  const densePoints = pickDenseCluster(normalized, Math.max(0.05, gridSize))
  const targetPoints = densePoints.length ? densePoints : normalized

  if (targetPoints.length === 1) {
    const point = targetPoints[0]
    map.setView([point.lat, point.lng], singlePointZoom, { animate: false })
    return true
  }

  const uniqueKeys = new Set(targetPoints.map((point) => `${point.lat.toFixed(6)}:${point.lng.toFixed(6)}`))
  if (uniqueKeys.size === 1) {
    const point = targetPoints[0]
    map.setView([point.lat, point.lng], singlePointZoom, { animate: false })
    return true
  }

  map.fitBounds(
    targetPoints.map((point) => [point.lat, point.lng]),
    {
      maxZoom,
      padding: [36, 36],
      animate: false,
    },
  )
  return true
}
