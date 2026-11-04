<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import L from 'leaflet'
import { getJson, postJson } from '../lib/api'
import { escapeHtml } from '../lib/escape'
import { focusMapToDenseRegion } from '../lib/mapFocus'
import { pushFlash } from '../stores/session'

const robots = ref([])
const deviceId = ref('')
const name = ref('')
const selectedRobotId = ref(null)
const editorVisible = ref(false)
const editorMode = ref('robot')
const robotEditName = ref('')
const robotEditStatus = ref('OFFLINE')

const patrolTasks = ref([])
const taskLoading = ref(false)
const taskSaving = ref(false)
const taskActionMessage = ref('')
const taskActionType = ref('info')
const editingTaskId = ref(null)
const taskName = ref('')
const taskStatus = ref('PAUSED')
const taskAreaText = ref('')
const taskPathText = ref('')

const MAP_PICK_POINT_LIMIT = 4
const taskPickMode = ref('none')
const taskAreaPoints = ref([])
const taskPathPoints = ref([])
const robotResolvedAddress = ref('')
const robotAddressLoading = ref(false)
const robotAddressError = ref('')
const robotAddressCache = new Map()

const markerMenu = reactive({
  visible: false,
  x: 0,
  y: 0,
  robotId: null,
})

let map = null
let pollTimer = null
let hasAutoFocused = false
let mapInteracted = false
const markers = {}
let taskOverlayLayer = null
let taskDraftOverlayLayer = null
let lastOverlapWarningKey = ''
const ROBOT_POLL_INTERVAL_MS = 500
const TASK_POLL_INTERVAL_MS = 1000
const MARKER_ANIMATION_MS = 420
let robotListLoading = false
let robotListPending = false
let taskPollTimer = null

const ROBOT_STATUSES = ['ONLINE', 'OFFLINE', 'PAUSED', 'ERROR']
const PATROL_STATUSES = [
  { value: 'PLANNED', label: '待执行' },
  { value: 'RUNNING', label: '执行中' },
  { value: 'PAUSED', label: '已暂停' },
  { value: 'DONE', label: '已完成' },
  { value: 'CANCELLED', label: '已取消' },
]

const selectedRobot = computed(() => robots.value.find((item) => String(item.id) === String(selectedRobotId.value)) || null)
const taskPickModeLabel = computed(() => {
  if (taskPickMode.value === 'area') return '巡检区域'
  if (taskPickMode.value === 'path') return '路径规划'
  return '未开启'
})
const selectedRobotAddressKey = computed(() => {
  if (!selectedRobot.value) return ''
  const lat = Number(selectedRobot.value.lat)
  const lng = Number(selectedRobot.value.lng)
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return ''
  return `${lat.toFixed(5)},${lng.toFixed(5)}`
})

function statusClass(status) {
  const token = String(status || 'unknown')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, '-')
  return `status-${token || 'unknown'}`
}

async function loadSelectedRobotAddress() {
  if (!selectedRobot.value) {
    robotResolvedAddress.value = ''
    robotAddressError.value = ''
    robotAddressLoading.value = false
    return
  }

  const lat = Number(selectedRobot.value.lat)
  const lng = Number(selectedRobot.value.lng)
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
    robotResolvedAddress.value = '暂无定位信息'
    robotAddressError.value = ''
    robotAddressLoading.value = false
    return
  }

  const cacheKey = selectedRobotAddressKey.value
  if (cacheKey && robotAddressCache.has(cacheKey)) {
    robotResolvedAddress.value = robotAddressCache.get(cacheKey) || ''
    robotAddressError.value = ''
    robotAddressLoading.value = false
    return
  }

  robotAddressLoading.value = true
  robotAddressError.value = ''
  try {
    const payload = await getJson(`/api/robot/address?lat=${encodeURIComponent(lat)}&lng=${encodeURIComponent(lng)}`)
    const rawAddress = String(payload.address || '').trim()
    const address = (/^not\s*found$/i.test(rawAddress) ? '' : rawAddress) || '未解析到详细地址'
    if (cacheKey) robotAddressCache.set(cacheKey, address)
    if (selectedRobotAddressKey.value === cacheKey) {
      robotResolvedAddress.value = address
    }
  } catch (error) {
    const fallback = `坐标：${lat.toFixed(5)}, ${lng.toFixed(5)}`
    if (selectedRobotAddressKey.value === cacheKey) {
      robotResolvedAddress.value = fallback
      robotAddressError.value = error.message || '地址解析失败'
    }
  } finally {
    if (selectedRobotAddressKey.value === cacheKey) {
      robotAddressLoading.value = false
    }
  }
}

function resetRobotForm() {
  deviceId.value = ''
  name.value = ''
}

function resetTaskForm() {
  editingTaskId.value = null
  taskName.value = ''
  taskStatus.value = 'PAUSED'
  taskAreaText.value = ''
  taskPathText.value = ''
  taskAreaPoints.value = []
  taskPathPoints.value = []
  taskPickMode.value = 'none'
  renderTaskGeometry()
}

function setTaskActionFeedback(message, type = 'info') {
  taskActionMessage.value = String(message || '').trim()
  taskActionType.value = type
}

function buildRobotPopup(robot) {
  return `<b>${escapeHtml(robot.name || '-')}</b><br>${escapeHtml(robot.device_id || '-')}`
}

function normalizePointList(rawPoints, maxPoints = MAP_PICK_POINT_LIMIT) {
  if (!Array.isArray(rawPoints)) return []
  return rawPoints
    .map((point) => ({ lat: Number(point?.lat), lng: Number(point?.lng) }))
    .filter((point) => Number.isFinite(point.lat) && Number.isFinite(point.lng))
    .filter((point) => point.lat >= -90 && point.lat <= 90 && point.lng >= -180 && point.lng <= 180)
    .slice(0, maxPoints)
}

function parseCoordinateLines(rawText, fieldLabel, minimumPoints = 0, allowEmpty = false) {
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

function formatCoordinateLines(points) {
  if (!Array.isArray(points) || !points.length) return ''
  return points.map((point) => `${Number(point.lat).toFixed(6)},${Number(point.lng).toFixed(6)}`).join('\n')
}

function renderTaskGeometry() {
  if (!map || !taskDraftOverlayLayer) return
  taskDraftOverlayLayer.clearLayers()

  taskAreaPoints.value.forEach((point) => {
    L.circleMarker([point.lat, point.lng], {
      radius: 5,
      color: '#d53f50',
      weight: 2,
      fillColor: '#ef7483',
      fillOpacity: 0.85,
    }).addTo(taskDraftOverlayLayer)
  })

  if (taskAreaPoints.value.length >= 3) {
    L.polygon(taskAreaPoints.value.map((point) => [point.lat, point.lng]), {
      color: '#d53f50',
      weight: 2,
      fillColor: '#ef7483',
      fillOpacity: 0.18,
    }).addTo(taskDraftOverlayLayer)
  } else if (taskAreaPoints.value.length >= 2) {
    L.polyline(taskAreaPoints.value.map((point) => [point.lat, point.lng]), {
      color: '#d53f50',
      weight: 2,
    }).addTo(taskDraftOverlayLayer)
  }

  taskPathPoints.value.forEach((point) => {
    L.circleMarker([point.lat, point.lng], {
      radius: 5,
      color: '#2563eb',
      weight: 2,
      fillColor: '#60a5fa',
      fillOpacity: 0.85,
    }).addTo(taskDraftOverlayLayer)
  })

  if (taskPathPoints.value.length >= 2) {
    L.polyline(taskPathPoints.value.map((point) => [point.lat, point.lng]), {
      color: '#2563eb',
      weight: 3,
      dashArray: '6 6',
    }).addTo(taskDraftOverlayLayer)
  }
}

function orientation(a, b, c) {
  const value = (b.lng - a.lng) * (c.lat - a.lat) - (b.lat - a.lat) * (c.lng - a.lng)
  if (Math.abs(value) < 1e-12) return 0
  return value > 0 ? 1 : -1
}

function onSegment(a, b, p) {
  return (
    p.lng <= Math.max(a.lng, b.lng) + 1e-12 &&
    p.lng + 1e-12 >= Math.min(a.lng, b.lng) &&
    p.lat <= Math.max(a.lat, b.lat) + 1e-12 &&
    p.lat + 1e-12 >= Math.min(a.lat, b.lat)
  )
}

function segmentsIntersect(a, b, c, d) {
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

function pointInPolygon(point, polygon) {
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

function polygonsOverlap(polyA, polyB) {
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

function renderPersistentTaskGeometry() {
  if (!map || !taskOverlayLayer) return
  taskOverlayLayer.clearLayers()

  patrolTasks.value.forEach((task) => {
    const areaPoints = normalizePointList(task.inspection_area || [])
    const pathPoints = normalizePointList(task.planned_path || [])
    const isRunning = String(task.status || '').toUpperCase() === 'RUNNING'
    const areaColor = isRunning ? '#f97316' : '#d53f50'
    const areaFillColor = isRunning ? '#fdba74' : '#ef7483'
    const pathColor = isRunning ? '#0f766e' : '#2563eb'
    const taskLabel = task.name || `任务 #${task.id}`

    areaPoints.forEach((point) => {
      L.circleMarker([point.lat, point.lng], {
        radius: 4,
        color: areaColor,
        weight: 1.5,
        fillColor: areaFillColor,
        fillOpacity: 0.72,
      }).bindTooltip(taskLabel).addTo(taskOverlayLayer)
    })

    if (areaPoints.length >= 3) {
      L.polygon(areaPoints.map((point) => [point.lat, point.lng]), {
        color: areaColor,
        weight: 2,
        fillColor: areaFillColor,
        fillOpacity: 0.14,
      }).bindTooltip(`${taskLabel} 检测区`).addTo(taskOverlayLayer)
    }

    pathPoints.forEach((point) => {
      L.circleMarker([point.lat, point.lng], {
        radius: 4,
        color: pathColor,
        weight: 1.5,
        fillColor: '#60a5fa',
        fillOpacity: 0.72,
      }).bindTooltip(taskLabel).addTo(taskOverlayLayer)
    })

    if (pathPoints.length >= 2) {
      L.polyline(pathPoints.map((point) => [point.lat, point.lng]), {
        color: pathColor,
        weight: 2.5,
        dashArray: '6 6',
        opacity: 0.88,
      }).bindTooltip(`${taskLabel} 路径`).addTo(taskOverlayLayer)
    }
  })
}

function warnIfInspectionAreasOverlap() {
  const overlaps = []

  for (let i = 0; i < patrolTasks.value.length; i += 1) {
    const taskA = patrolTasks.value[i]
    const areaA = normalizePointList(taskA?.inspection_area || [])
    if (areaA.length < 3) continue

    for (let j = i + 1; j < patrolTasks.value.length; j += 1) {
      const taskB = patrolTasks.value[j]
      const areaB = normalizePointList(taskB?.inspection_area || [])
      if (areaB.length < 3) continue

      if (polygonsOverlap(areaA, areaB)) {
        overlaps.push(`${taskA?.name || `任务#${taskA?.id}`} 与 ${taskB?.name || `任务#${taskB?.id}`}`)
      }
    }
  }

  if (!overlaps.length) {
    lastOverlapWarningKey = ''
    return
  }

  const warningKey = overlaps.join('|')
  if (warningKey === lastOverlapWarningKey) return
  lastOverlapWarningKey = warningKey

  const warningMessage = `检测区存在重合：${overlaps.join('；')}`
  setTaskActionFeedback(warningMessage, 'warning')
  pushFlash(warningMessage, 'warning')
  window.alert(warningMessage)
}

function hideMarkerMenu() {
  markerMenu.visible = false
  markerMenu.robotId = null
}

function showMarkerMenu(robotId, event) {
  const nativeEvent = event?.originalEvent
  if (nativeEvent) {
    nativeEvent.preventDefault()
    nativeEvent.stopPropagation()
  }
  openEditor(robotId, 'robot')
}

function syncRobotEditorFromSelected() {
  if (!selectedRobot.value) return
  robotEditName.value = selectedRobot.value.name || ''
  robotEditStatus.value = selectedRobot.value.status || 'OFFLINE'
}

function openEditor(robotId, mode) {
  selectedRobotId.value = String(robotId)
  editorMode.value = mode
  editorVisible.value = true
  syncRobotEditorFromSelected()
  hideMarkerMenu()
  if (mode === 'task') {
    resetTaskForm()
    loadPatrolTasks()
  }
}

function closeEditor() {
  editorVisible.value = false
  taskPickMode.value = 'none'
}

function startTaskPickMode(mode) {
  if (!selectedRobotId.value) {
    pushFlash('请先右键选择一个机器人', 'warning')
    return
  }
  taskPickMode.value = mode
  setTaskActionFeedback(`已开启${mode === 'area' ? '巡检区域' : '路径规划'}选四点模式，请点击地图`, 'info')
}

function stopTaskPickMode() {
  taskPickMode.value = 'none'
}

function clearAreaPoints() {
  taskAreaPoints.value = []
  taskAreaText.value = ''
  renderTaskGeometry()
}

function clearPathPoints() {
  taskPathPoints.value = []
  taskPathText.value = ''
  renderTaskGeometry()
}

function applyTextToMapPreview() {
  try {
    const areaPoints = parseCoordinateLines(taskAreaText.value, '巡检区域', 3, false)
    const pathPoints = parseCoordinateLines(taskPathText.value, '规划路径', 2, true)
    if (areaPoints.length !== MAP_PICK_POINT_LIMIT) throw new Error(`巡检区域必须是 ${MAP_PICK_POINT_LIMIT} 个点`)
    if (pathPoints.length !== 0 && pathPoints.length !== MAP_PICK_POINT_LIMIT) throw new Error(`规划路径为空或必须是 ${MAP_PICK_POINT_LIMIT} 个点`)

    taskAreaPoints.value = normalizePointList(areaPoints)
    taskPathPoints.value = normalizePointList(pathPoints)
    renderTaskGeometry()
    setTaskActionFeedback('已根据文本刷新地图预览', 'success')
  } catch (error) {
    setTaskActionFeedback(error.message || '文本坐标解析失败', 'error')
  }
}

function handleTaskMapClick(event) {
  if (!editorVisible.value || editorMode.value !== 'task' || taskPickMode.value === 'none') {
    return
  }
  const point = {
    lat: Number(event.latlng.lat.toFixed(6)),
    lng: Number(event.latlng.lng.toFixed(6)),
  }

  if (taskPickMode.value === 'area') {
    if (taskAreaPoints.value.length >= MAP_PICK_POINT_LIMIT) {
      taskPickMode.value = 'none'
      return
    }
    taskAreaPoints.value = [...taskAreaPoints.value, point]
    taskAreaText.value = formatCoordinateLines(taskAreaPoints.value)
    renderTaskGeometry()
    if (taskAreaPoints.value.length >= MAP_PICK_POINT_LIMIT) taskPickMode.value = 'none'
    return
  }

  if (taskPathPoints.value.length >= MAP_PICK_POINT_LIMIT) {
    taskPickMode.value = 'none'
    return
  }
  taskPathPoints.value = [...taskPathPoints.value, point]
  taskPathText.value = formatCoordinateLines(taskPathPoints.value)
  renderTaskGeometry()
  if (taskPathPoints.value.length >= MAP_PICK_POINT_LIMIT) taskPickMode.value = 'none'
}

function renderMarkers(robotList) {
  const stopMarkerAnimation = (marker) => {
    if (marker && marker.__animFrame) {
      window.cancelAnimationFrame(marker.__animFrame)
      marker.__animFrame = null
    }
  }

  const animateMarkerTo = (marker, nextLat, nextLng) => {
    if (!marker) return

    const current = marker.getLatLng()
    const startLat = Number(current?.lat)
    const startLng = Number(current?.lng)
    const endLat = Number(nextLat)
    const endLng = Number(nextLng)

    if (!Number.isFinite(startLat) || !Number.isFinite(startLng) || !Number.isFinite(endLat) || !Number.isFinite(endLng)) {
      marker.setLatLng([nextLat, nextLng])
      return
    }

    const deltaLat = endLat - startLat
    const deltaLng = endLng - startLng
    if (Math.abs(deltaLat) + Math.abs(deltaLng) < 1e-10) {
      marker.setLatLng([endLat, endLng])
      return
    }

    stopMarkerAnimation(marker)
    const startedAt = performance.now()
    const step = (now) => {
      const t = Math.min((now - startedAt) / MARKER_ANIMATION_MS, 1)
      const eased = t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2
      marker.setLatLng([startLat + deltaLat * eased, startLng + deltaLng * eased])
      if (t < 1) {
        marker.__animFrame = window.requestAnimationFrame(step)
      } else {
        marker.__animFrame = null
      }
    }
    marker.__animFrame = window.requestAnimationFrame(step)
  }

  const activeIds = new Set()
  robotList.forEach((robot) => {
    if (robot.lat == null || robot.lng == null || !map) return
    const markerId = String(robot.id)
    activeIds.add(markerId)
    if (markers[markerId]) {
      animateMarkerTo(markers[markerId], robot.lat, robot.lng)
      markers[markerId].setPopupContent(buildRobotPopup(robot))
      return
    }
    const marker = L.marker([robot.lat, robot.lng], {
      icon: L.divIcon({ className: 'map-dot-icon', html: '<span class="map-dot map-dot-robot"></span>', iconSize: [12, 12], iconAnchor: [6, 6] }),
    }).addTo(map).bindPopup(buildRobotPopup(robot))
    marker.on('click', () => {
      selectedRobotId.value = String(robot.id)
      syncRobotEditorFromSelected()
    })
    marker.on('contextmenu', (event) => showMarkerMenu(robot.id, event))
    markers[markerId] = marker
  })

  Object.keys(markers).forEach((markerId) => {
    if (activeIds.has(markerId)) return
    stopMarkerAnimation(markers[markerId])
    map.removeLayer(markers[markerId])
    delete markers[markerId]
  })
}

async function loadRobots() {
  if (robotListLoading) {
    robotListPending = true
    return
  }
  robotListLoading = true
  try {
    let payload
    try {
      payload = await getJson('/api/robot/live/list')
    } catch (liveError) {
      payload = await getJson('/api/robot/list')
    }
    const rawRobots = payload.robots || []
    robots.value = [...rawRobots].sort((a, b) => Number(b.id || 0) - Number(a.id || 0))

    if (!robots.value.length) {
      selectedRobotId.value = null
      patrolTasks.value = []
      closeEditor()
    } else if (!robots.value.some((item) => String(item.id) === String(selectedRobotId.value))) {
      selectedRobotId.value = String(robots.value[0].id)
    }

    renderMarkers(robots.value)
    if (selectedRobot.value) syncRobotEditorFromSelected()

    if (!mapInteracted && !hasAutoFocused) {
      const focusPoints = robots.value.map((item) => ({ lat: item.lat, lng: item.lng }))
      hasAutoFocused = focusMapToDenseRegion(map, focusPoints, { gridSize: 0.24, maxZoom: 16, singlePointZoom: 16 })
    }
  } catch (error) {
    pushFlash(error.message || '机器人列表加载失败', 'error')
  } finally {
    robotListLoading = false
    if (robotListPending) {
      robotListPending = false
      window.setTimeout(() => {
        loadRobots()
      }, 0)
    }
  }
}

async function addRobot() {
  try {
    const payload = await postJson('/api/robot/register', { device_id: deviceId.value.trim(), name: name.value.trim() })
    if (!payload.ok) {
      throw new Error(payload.msg || '添加失败')
    }
    resetRobotForm()
    await loadRobots()
    pushFlash('机器人添加成功', 'success')
  } catch (error) {
    pushFlash(error.message || '添加失败', 'error')
  }
}

async function saveRobotProfile() {
  if (!selectedRobot.value) {
    pushFlash('请先选择机器人', 'warning')
    return
  }
  const newName = String(robotEditName.value || '').trim()
  if (!newName) {
    pushFlash('机器人名称不能为空', 'warning')
    return
  }
  try {
    await postJson('/api/robot/update', {
      id: Number(selectedRobot.value.id),
      name: newName,
      status: robotEditStatus.value,
    })
    await loadRobots()
    pushFlash('机器人信息已更新', 'success')
  } catch (error) {
    pushFlash(error.message || '机器人信息更新失败', 'error')
  }
}

async function deleteRobot(robotId) {
  if (!window.confirm('确认删除该机器人？')) return
  try {
    await postJson(`/api/robot/delete/${robotId}`, {})
    if (String(selectedRobotId.value) === String(robotId)) {
      selectedRobotId.value = null
      closeEditor()
    }
    await loadRobots()
    pushFlash('机器人已删除', 'success')
  } catch (error) {
    pushFlash(error.message || '删除失败', 'error')
  }
}

async function loadPatrolTasks(options = {}) {
  const silent = Boolean(options?.silent)
  if (!selectedRobotId.value) {
    patrolTasks.value = []
    renderPersistentTaskGeometry()
    lastOverlapWarningKey = ''
    return
  }

  const previousStatusByTaskId = new Map(
    (patrolTasks.value || []).map((task) => [Number(task.id), String(task.status || '').toUpperCase()]),
  )

  taskLoading.value = true
  try {
    const payload = await getJson(`/api/robot/task/list?robot_id=${Number(selectedRobotId.value)}`)
    patrolTasks.value = payload.tasks || []
    renderPersistentTaskGeometry()
    warnIfInspectionAreasOverlap()

    const newlyDoneTasks = patrolTasks.value.filter((task) => {
      const currentStatus = String(task?.status || '').toUpperCase()
      const previousStatus = previousStatusByTaskId.get(Number(task?.id))
      return previousStatus === 'RUNNING' && currentStatus === 'DONE'
    })
    if (newlyDoneTasks.length) {
      const taskNames = newlyDoneTasks.map((task) => task?.name || `任务#${task?.id}`).join('、')
      const successMessage = `巡检任务已完成：${taskNames}`
      setTaskActionFeedback(successMessage, 'success')
      pushFlash(successMessage, 'success')
    } else if (!silent) {
      setTaskActionFeedback(`已加载 ${patrolTasks.value.length} 条巡检任务`, 'info')
    }
  } catch (error) {
    if (!silent) {
      setTaskActionFeedback(error.message || '巡检任务加载失败', 'error')
    }
  } finally {
    taskLoading.value = false
  }
}

function startTaskPolling() {
  if (taskPollTimer) return
  taskPollTimer = window.setInterval(() => {
    if (!editorVisible.value || editorMode.value !== 'task' || !selectedRobotId.value) return
    loadPatrolTasks({ silent: true })
  }, TASK_POLL_INTERVAL_MS)
}

function stopTaskPolling() {
  if (!taskPollTimer) return
  window.clearInterval(taskPollTimer)
  taskPollTimer = null
}

async function loadTaskDetail(taskId) {
  try {
    const payload = await getJson(`/api/robot/task/${taskId}`)
    const task = payload.task || null
    if (!task) throw new Error('任务不存在')

    editingTaskId.value = task.id
    taskName.value = task.name || ''
    taskStatus.value = task.status || 'PLANNED'
    taskAreaPoints.value = normalizePointList(task.inspection_area || [])
    taskPathPoints.value = normalizePointList(task.planned_path || [])
    taskAreaText.value = formatCoordinateLines(taskAreaPoints.value)
    taskPathText.value = formatCoordinateLines(taskPathPoints.value)
    taskPickMode.value = 'none'
    renderTaskGeometry()
    setTaskActionFeedback(`已加载任务 #${task.id}`, 'info')
  } catch (error) {
    setTaskActionFeedback(error.message || '任务详情加载失败', 'error')
  }
}

async function savePatrolTask() {
  if (!selectedRobotId.value) {
    setTaskActionFeedback('请先选择机器人', 'warning')
    return
  }

  let inspectionArea = []
  let plannedPath = []
  try {
    inspectionArea = parseCoordinateLines(taskAreaText.value, '巡检区域', 3, false)
    plannedPath = parseCoordinateLines(taskPathText.value, '规划路径', 2, true)
    if (inspectionArea.length !== MAP_PICK_POINT_LIMIT) throw new Error(`巡检区域必须是 ${MAP_PICK_POINT_LIMIT} 个点`)
    if (plannedPath.length !== 0 && plannedPath.length !== MAP_PICK_POINT_LIMIT) throw new Error(`规划路径为空或必须是 ${MAP_PICK_POINT_LIMIT} 个点`)
  } catch (error) {
    setTaskActionFeedback(error.message || '任务坐标格式错误', 'error')
    return
  }

  const payload = {
    name: String(taskName.value || '').trim(),
    inspection_area: inspectionArea,
    planned_path: plannedPath,
    status: taskStatus.value,
  }

  if (!payload.name) {
    setTaskActionFeedback('任务名称不能为空', 'warning')
    return
  }

  taskSaving.value = true
  setTaskActionFeedback(editingTaskId.value ? '正在更新巡检任务...' : '正在创建巡检任务...', 'info')
  try {
    if (editingTaskId.value) {
      const updateResp = await postJson(`/api/robot/task/update/${editingTaskId.value}`, payload)
      const updatedTask = updateResp.task || null
      if (updatedTask?.id) editingTaskId.value = updatedTask.id
      setTaskActionFeedback('巡检任务已更新', 'success')
    } else {
      const createResp = await postJson('/api/robot/task/create', {
        robot_id: Number(selectedRobotId.value),
        ...payload,
      })
      const createdTask = createResp.task || null
      if (createdTask?.id) editingTaskId.value = createdTask.id
      setTaskActionFeedback('巡检任务已创建', 'success')
    }
    taskAreaPoints.value = normalizePointList(inspectionArea)
    taskPathPoints.value = normalizePointList(plannedPath)
    taskPickMode.value = 'none'
    renderTaskGeometry()
    await loadPatrolTasks()
  } catch (error) {
    setTaskActionFeedback(error.message || '巡检任务保存失败', 'error')
  } finally {
    taskSaving.value = false
  }
}

async function setTaskStatus(taskId, status) {
  try {
    await postJson(`/api/robot/task/update/${taskId}`, { status })
    await loadPatrolTasks()
  } catch (error) {
    setTaskActionFeedback(error.message || '任务状态更新失败', 'error')
  }
}

async function deletePatrolTask(taskId) {
  if (!window.confirm('确认删除该巡检任务？')) return
  try {
    await postJson(`/api/robot/task/delete/${taskId}`, {})
    if (Number(editingTaskId.value) === Number(taskId)) resetTaskForm()
    await loadPatrolTasks()
    setTaskActionFeedback('巡检任务已删除', 'success')
  } catch (error) {
    setTaskActionFeedback(error.message || '巡检任务删除失败', 'error')
  }
}

async function navigateRobot(event) {
  if (taskPickMode.value !== 'none') return
  if (!selectedRobotId.value) return

  const latitude = event.latlng.lat
  const longitude = event.latlng.lng
  if (!window.confirm(`确认让设备 ${selectedRobotId.value} 导航到 (${latitude.toFixed(5)}, ${longitude.toFixed(5)}) ?`)) return

  try {
    await postJson('/api/robot/navigate', {
      id: Number(selectedRobotId.value),
      lat: latitude,
      lng: longitude,
    })
    pushFlash('导航命令已发送', 'success')
  } catch (error) {
    pushFlash(error.message || '导航失败', 'error')
  }
}

function onResize() {
  map?.invalidateSize()
}

watch(selectedRobotId, () => {
  syncRobotEditorFromSelected()
  if (editorVisible.value && editorMode.value === 'task') {
    resetTaskForm()
  }
  loadPatrolTasks()
})

watch([selectedRobotAddressKey, editorVisible], ([addressKey, visible]) => {
  if (!visible || !addressKey) {
    if (!visible) {
      robotAddressLoading.value = false
      robotAddressError.value = ''
    }
    return
  }
  loadSelectedRobotAddress()
}, { immediate: true })

watch(editorMode, (mode) => {
  if (!editorVisible.value) return
  if (mode === 'task') {
    resetTaskForm()
    loadPatrolTasks()
  }
})

watch([editorVisible, editorMode, selectedRobotId], ([visible, mode, robotId]) => {
  if (visible && mode === 'task' && robotId) {
    loadPatrolTasks({ silent: true })
    startTaskPolling()
    return
  }
  stopTaskPolling()
})

onMounted(() => {
  map = L.map('robotMap').setView([30, 110], 5)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(map)
  taskOverlayLayer = L.layerGroup().addTo(map)
  taskDraftOverlayLayer = L.layerGroup().addTo(map)
  map.on('click', (event) => {
    hideMarkerMenu()
    handleTaskMapClick(event)
  })
  map.on('contextmenu', () => hideMarkerMenu())
  map.on('dblclick', navigateRobot)
  map.on('dragstart zoomstart', () => {
    mapInteracted = true
  })

  loadRobots()
  pollTimer = window.setInterval(loadRobots, ROBOT_POLL_INTERVAL_MS)
  window.setTimeout(() => map?.invalidateSize(), 300)
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  stopTaskPolling()
  Object.keys(markers).forEach((markerId) => {
    const marker = markers[markerId]
    if (marker && marker.__animFrame) {
      window.cancelAnimationFrame(marker.__animFrame)
      marker.__animFrame = null
    }
  })
  window.removeEventListener('resize', onResize)
  map?.remove()
})
</script>

<template>
  <div class="robot-admin-page">
    <div class="map-toolbar">
      <div class="toolbar-title">机器人任务部署</div>
      <div class="toolbar-row">
        <input v-model.trim="deviceId" class="input-control toolbar-input" placeholder="设备ID">
        <input v-model.trim="name" class="input-control toolbar-input" placeholder="名称">
        <button type="button" class="square-btn" @click="addRobot">添加机器人</button>
        <button type="button" class="square-btn" @click="loadRobots">刷新</button>
      </div>
      <div class="toolbar-sub">双击地图可向当前选中机器人下发导航；右键机器人点直接打开详情管理面板。</div>
    </div>

    <div id="robotMap" class="robot-map-full"></div>

    <div v-if="markerMenu.visible" class="marker-context-menu"
      :style="{ left: `${markerMenu.x}px`, top: `${markerMenu.y}px` }">
      <button type="button" class="square-btn" @click="openEditor(markerMenu.robotId, 'robot')">编辑机器人</button>
      <button type="button" class="square-btn" @click="openEditor(markerMenu.robotId, 'task')">编辑巡检任务</button>
      <button type="button" class="square-btn btn-delete" @click="deleteRobot(markerMenu.robotId)">删除机器人</button>
      <button type="button" class="square-btn" @click="hideMarkerMenu">关闭</button>
    </div>

    <div v-if="editorVisible && selectedRobot" class="editor-drawer">
      <div class="drawer-head">
        <div class="drawer-identity">
          <div class="drawer-title">{{ selectedRobot.name || '-' }} #{{ selectedRobot.id }}</div>
          <div class="drawer-subtitle">设备ID：{{ selectedRobot.device_id || '-' }}</div>
          <div class="drawer-meta-row">
            <span class="status-chip" :class="statusClass(selectedRobot.status)">{{ selectedRobot.status || 'UNKNOWN' }}</span>
            <span class="meta-chip">电量 {{ selectedRobot.battery ?? '-' }}%</span>
          </div>
        </div>
        <button type="button" class="square-btn btn-ghost" @click="closeEditor">关闭</button>
      </div>

      <div class="drawer-mode-switch">
        <button type="button" class="square-btn" :class="{ 'square-btn-active': editorMode === 'robot' }"
          @click="editorMode = 'robot'">
          机器人管理
        </button>
        <button type="button" class="square-btn" :class="{ 'square-btn-active': editorMode === 'task' }"
          @click="editorMode = 'task'">
          巡检任务管理
        </button>
      </div>

      <div v-if="editorMode === 'robot'" class="drawer-body">
        <div class="robot-quick-grid">
          <div class="quick-card">
            <div class="quick-label">在线状态</div>
            <div class="quick-value" :class="statusClass(selectedRobot.status)">{{ selectedRobot.status || 'UNKNOWN' }}</div>
          </div>
          <div class="quick-card quick-card-wide">
            <div class="quick-label">当前位置</div>
            <div class="quick-value quick-address-value">{{ robotAddressLoading ? '地址解析中...' : (robotResolvedAddress || '暂无定位信息') }}</div>
            <div v-if="robotAddressError" class="quick-subvalue">{{ robotAddressError }}</div>
          </div>
        </div>

        <input v-model.trim="robotEditName" class="input-control" placeholder="机器人名称">
        <select v-model="robotEditStatus" class="input-control">
          <option v-for="status in ROBOT_STATUSES" :key="status" :value="status">{{ status }}</option>
        </select>
        <div class="drawer-actions robot-actions">
          <button type="button" class="square-btn robot-action-btn" @click="saveRobotProfile">保存机器人</button>
          <button type="button" class="square-btn btn-delete robot-action-btn" @click="deleteRobot(selectedRobot.id)">删除机器人</button>
          <RouterLink class="square-btn robot-action-btn" :to="`/robot/${selectedRobot.id}`">手动控制</RouterLink>
        </div>
      </div>

      <div v-if="editorMode === 'task'" class="drawer-body task-drawer-body">
        <div class="task-map-tools">
          <button type="button" class="square-btn" :class="{ 'square-btn-active': taskPickMode === 'area' }"
            @click="startTaskPickMode('area')">地图选四点-区域</button>
          <button type="button" class="square-btn" :class="{ 'square-btn-active': taskPickMode === 'path' }"
            @click="startTaskPickMode('path')">地图选四点-路径</button>
          <button type="button" class="square-btn" @click="stopTaskPickMode">停止选点</button>
        </div>

        <div class="task-map-hint">模式：{{ taskPickModeLabel }} ｜ 区域 {{ taskAreaPoints.length }}/{{ MAP_PICK_POINT_LIMIT
          }} ｜ 路径 {{ taskPathPoints.length }}/{{ MAP_PICK_POINT_LIMIT }}</div>

        <input v-model.trim="taskName" class="input-control" placeholder="任务名称，例如：校园北区早巡">
        <select v-model="taskStatus" class="input-control">
          <option v-for="item in PATROL_STATUSES" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>

        <div class="task-textarea-head">
          <span>巡检区域坐标（固定 4 点）</span>
          <button type="button" class="square-btn" @click="clearAreaPoints">清空区域</button>
        </div>
        <textarea v-model="taskAreaText" class="input-control task-textarea"
          placeholder="每行一个点：\n30.123456,120.123456\n30.223456,120.223456\n30.323456,120.323456\n30.423456,120.423456"></textarea>

        <div class="task-textarea-head">
          <span>规划路径坐标（为空或固定 4 点）</span>
          <button type="button" class="square-btn" @click="clearPathPoints">清空路径</button>
        </div>
        <textarea v-model="taskPathText" class="input-control task-textarea"
          placeholder="每行一个点：\n30.120000,120.120000\n30.220000,120.220000\n30.320000,120.320000\n30.420000,120.420000"></textarea>

        <div class="drawer-actions">
          <button type="button" class="square-btn" :disabled="taskSaving" @click="savePatrolTask">{{ taskSaving ?
            '提交中...' : (editingTaskId ? '保存更新' : '新建任务') }}</button>
          <button type="button" class="square-btn" @click="resetTaskForm">重置</button>
        </div>

        <div v-if="taskActionMessage" class="task-action-feedback" :class="`task-action-${taskActionType}`">{{
          taskActionMessage }}</div>
        <div v-if="editingTaskId" class="task-editing-tip">当前编辑任务 #{{ editingTaskId }}</div>

        <div class="task-list-wrap">
          <div v-if="taskLoading" class="empty-state">任务载入中...</div>
          <template v-else>
            <div v-for="task in patrolTasks" :key="task.id" class="task-list-item">
              <div class="task-item-head">
                <span class="task-item-name">{{ task.name }}</span>
                <span class="task-item-status" :class="statusClass(task.status)">{{ task.status }}</span>
              </div>
              <div class="task-item-meta">创建时间：{{ task.created_at || '-' }}</div>
              <div class="task-item-actions">
                <button type="button" class="square-btn" @click="loadTaskDetail(task.id)">编辑</button>
                <button type="button" class="square-btn" @click="setTaskStatus(task.id, 'RUNNING')">运行</button>
                <button type="button" class="square-btn" @click="setTaskStatus(task.id, 'PAUSED')">暂停</button>
                <button type="button" class="square-btn" @click="setTaskStatus(task.id, 'DONE')">完成</button>
                <button type="button" class="square-btn btn-delete" @click="deletePatrolTask(task.id)">删除</button>
              </div>
            </div>
            <div v-if="!patrolTasks.length" class="empty-state">暂无巡检任务</div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.robot-admin-page {
  --panel-bg: rgba(255, 255, 255, 0.84);
  --panel-border: rgba(255, 255, 255, 0.46);
  --ink-strong: #13263d;
  --ink-soft: #556579;
  --brand: #0f8b8d;
  --brand-deep: #136f80;
  --accent: #f4a261;
  position: relative;
  width: 100%;
  height: calc(100vh - 120px);
  min-height: 640px;
  font-family: 'Noto Sans SC', 'Microsoft YaHei UI', 'PingFang SC', sans-serif;
}

.map-toolbar {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 600;
  width: min(760px, calc(100% - 24px));
  padding: 12px;
  border-radius: 16px;
  border: 1px solid var(--panel-border);
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.95), var(--panel-bg));
  backdrop-filter: blur(8px);
  box-shadow: 0 18px 36px rgba(16, 37, 63, 0.18);
  display: grid;
  gap: 10px;
}

.toolbar-title {
  font-size: 15px;
  font-weight: 800;
  color: var(--ink-strong);
  letter-spacing: 0.02em;
}

.toolbar-row {
  display: grid;
  grid-template-columns: minmax(140px, 1fr) minmax(140px, 1fr) auto auto;
  gap: 8px;
}

.toolbar-input {
  min-height: 40px;
}

.toolbar-sub {
  font-size: 12px;
  color: var(--ink-soft);
}

.robot-map-full {
  width: 100%;
  height: 100%;
  border-radius: 16px;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.5);
}

.square-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  min-width: 90px;
  padding: 0 14px;
  border-radius: 10px;
  text-decoration: none;
  border: 1px solid transparent;
  background: linear-gradient(140deg, var(--brand), var(--brand-deep));
  color: #ffffff;
  font-weight: 700;
  transition: transform 0.16s ease, box-shadow 0.16s ease, filter 0.16s ease;
}

.square-btn:hover {
  transform: translateY(-1px);
  filter: brightness(1.03);
  box-shadow: 0 9px 18px rgba(15, 139, 141, 0.26);
}

.square-btn:active {
  transform: translateY(0);
}

.square-btn-active {
  box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.66), 0 10px 20px rgba(19, 111, 128, 0.3);
}

.btn-ghost {
  background: rgba(16, 36, 60, 0.08);
  border-color: rgba(16, 36, 60, 0.14);
  color: var(--ink-strong);
}

.btn-ghost:hover {
  box-shadow: 0 10px 20px rgba(12, 37, 63, 0.14);
}

.marker-context-menu {
  position: fixed;
  z-index: 1000;
  display: grid;
  gap: 6px;
  padding: 10px;
  border-radius: 14px;
  border: 1px solid var(--panel-border);
  background: linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(236, 247, 247, 0.95));
  box-shadow: 0 18px 30px rgba(12, 37, 63, 0.2);
  min-width: 156px;
}

.editor-drawer {
  position: absolute;
  top: 120px;
  right: 12px;
  bottom: 12px;
  width: min(440px, calc(100% - 24px));
  z-index: 700;
  border-radius: 16px;
  border: 1px solid var(--panel-border);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.97), rgba(248, 252, 252, 0.95));
  backdrop-filter: blur(10px);
  box-shadow: 0 22px 36px rgba(13, 40, 70, 0.26);
  display: grid;
  grid-template-rows: auto auto 1fr;
  overflow: hidden;
  animation: drawer-in 0.26s ease;
}

.drawer-head {
  padding: 12px;
  border-bottom: 1px solid rgba(15, 36, 61, 0.08);
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.drawer-identity {
  display: grid;
  gap: 4px;
}

.drawer-title {
  font-size: 16px;
  font-weight: 800;
  color: var(--ink-strong);
}

.drawer-subtitle {
  font-size: 12px;
  color: var(--ink-soft);
}

.drawer-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.status-chip,
.meta-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  padding: 0 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.meta-chip {
  background: rgba(15, 139, 141, 0.12);
  color: #0d5f61;
}

.drawer-mode-switch {
  padding: 10px 12px;
  display: flex;
  gap: 10px;
  border-bottom: 1px solid rgba(15, 36, 61, 0.08);
}

.drawer-body {
  padding: 12px;
  overflow: auto;
  display: grid;
  gap: 10px;
}

.robot-quick-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.quick-card-wide {
  grid-column: span 2;
}

.quick-card {
  border: 1px solid rgba(15, 36, 61, 0.08);
  border-radius: 12px;
  padding: 8px;
  background: rgba(255, 255, 255, 0.74);
  display: grid;
  gap: 4px;
}

.quick-label {
  font-size: 11px;
  color: var(--ink-soft);
}

.quick-value {
  font-size: 13px;
  font-weight: 800;
  color: var(--ink-strong);
}

.quick-address-value {
  line-height: 1.45;
  word-break: break-word;
}

.quick-subvalue {
  font-size: 11px;
  color: var(--ink-soft);
  line-height: 1.4;
}

.drawer-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.robot-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.robot-actions .square-btn {
  width: 100%;
  min-width: 0;
}

.robot-action-btn {
  box-sizing: border-box;
  height: 42px;
  min-height: 42px;
  line-height: 1;
}

.task-drawer-body {
  align-content: start;
}

.task-map-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.task-map-hint {
  color: var(--ink-soft);
  font-size: 12px;
}

.task-textarea-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  color: #304559;
  font-size: 12px;
  font-weight: 600;
}

.task-textarea {
  min-height: 82px;
  resize: vertical;
}

.task-editing-tip {
  font-size: 12px;
  color: #0d7f5a;
}

.task-action-feedback {
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12px;
  font-weight: 600;
}

.task-action-info {
  background: rgba(59, 130, 246, 0.12);
  color: #1e40af;
}

.task-action-success {
  background: rgba(16, 185, 129, 0.14);
  color: #0f6f52;
}

.task-action-warning {
  background: rgba(245, 158, 11, 0.14);
  color: #92400e;
}

.task-action-error {
  background: rgba(239, 68, 68, 0.14);
  color: #991b1b;
}

.task-list-wrap {
  display: grid;
  gap: 8px;
}

.task-list-item {
  border: 1px solid rgba(15, 36, 61, 0.1);
  border-radius: 12px;
  padding: 10px;
  background: rgba(255, 255, 255, 0.9);
  display: grid;
  gap: 6px;
}

.task-item-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.task-item-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--ink-strong);
}

.task-item-status {
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  font-weight: 700;
}

.task-item-meta {
  color: var(--ink-soft);
  font-size: 12px;
}

.task-item-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.status-online,
.status-running {
  background: rgba(16, 185, 129, 0.16);
  color: #0d7d5b;
}

.status-offline,
.status-paused,
.status-planned {
  background: rgba(148, 163, 184, 0.2);
  color: #344557;
}

.status-error,
.status-cancelled {
  background: rgba(239, 68, 68, 0.18);
  color: #a12424;
}

.status-done {
  background: rgba(79, 70, 229, 0.16);
  color: #3f3cbb;
}

.status-unknown {
  background: rgba(15, 36, 61, 0.1);
  color: #304559;
}

@keyframes drawer-in {
  from {
    opacity: 0;
    transform: translateX(14px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@media (max-width: 980px) {
  .robot-admin-page {
    height: calc(100vh - 96px);
  }

  .toolbar-row {
    grid-template-columns: 1fr 1fr;
  }

  .editor-drawer {
    top: 180px;
    width: calc(100% - 24px);
  }

  .robot-quick-grid {
    grid-template-columns: 1fr;
  }

  .robot-actions {
    grid-template-columns: 1fr;
  }

  .quick-card-wide {
    grid-column: span 1;
  }
}
</style>
