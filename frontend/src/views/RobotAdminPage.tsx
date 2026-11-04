import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import L from 'leaflet'
import { useLiveState } from '../hooks/useLiveState'
import { errorMessage, getJson, postJson } from '../lib/api'
import { escapeHtml } from '../lib/escape'
import { focusMapToDenseRegion } from '../lib/mapFocus'
import {
  MAP_PICK_POINT_LIMIT,
  formatCoordinateLines,
  normalizePointList,
  parseTaskGeometry,
  polygonsOverlap,
  type LatLngPoint,
} from '../lib/patrolGeometry'
import { pushFlash } from '../stores/session'
import './RobotAdminPage.css'

interface Robot {
  id: number
  device_id?: string | null
  name?: string | null
  status?: string | null
  battery?: number | null
  lat?: number | null
  lng?: number | null
}

interface PatrolTask {
  id: number
  name?: string | null
  status?: string | null
  inspection_area?: LatLngPoint[]
  planned_path?: LatLngPoint[]
  created_at?: string | null
}

type EditorMode = 'robot' | 'task'
type PickMode = 'none' | 'area' | 'path'
type FeedbackType = 'info' | 'success' | 'warning' | 'error'

const ROBOT_POLL_INTERVAL_MS = 500
const TASK_POLL_INTERVAL_MS = 1000
const MARKER_ANIMATION_MS = 420

const ROBOT_STATUSES = ['ONLINE', 'OFFLINE', 'PAUSED', 'ERROR']
const PATROL_STATUSES = [
  { value: 'PLANNED', label: '待执行' },
  { value: 'RUNNING', label: '执行中' },
  { value: 'PAUSED', label: '已暂停' },
  { value: 'DONE', label: '已完成' },
  { value: 'CANCELLED', label: '已取消' },
]

const AREA_PLACEHOLDER = '每行一个点：\n30.123456,120.123456\n30.223456,120.223456\n30.323456,120.323456\n30.423456,120.423456'
const PATH_PLACEHOLDER = '每行一个点：\n30.120000,120.120000\n30.220000,120.220000\n30.320000,120.320000\n30.420000,120.420000'

function statusClass(status?: string | null) {
  const token = String(status || 'unknown')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, '-')
  return `status-${token || 'unknown'}`
}

function buildRobotPopup(robot: Robot) {
  return `<b>${escapeHtml(robot.name || '-')}</b><br>${escapeHtml(robot.device_id || '-')}`
}

function addressKeyOf(robot: Robot | null) {
  if (!robot) return ''
  const lat = Number(robot.lat)
  const lng = Number(robot.lng)
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return ''
  return `${lat.toFixed(5)},${lng.toFixed(5)}`
}

function taskLabel(task: PatrolTask | undefined) {
  return task?.name || `任务#${task?.id}`
}

export default function RobotAdminPage() {
  // --- Rendered state (with refs for imperative map/timer code where needed) ---
  const [robots, setRobots, robotsRef] = useLiveState<Robot[]>([])
  const [selectedRobotId, setSelectedRobotId, selectedRobotIdRef] = useLiveState<string | null>(null)
  const [editorVisible, setEditorVisible, editorVisibleRef] = useLiveState(false)
  const [editorMode, setEditorMode, editorModeRef] = useLiveState<EditorMode>('robot')
  const [patrolTasks, setPatrolTasks, patrolTasksRef] = useLiveState<PatrolTask[]>([])
  const [taskPickMode, setTaskPickMode, taskPickModeRef] = useLiveState<PickMode>('none')
  const [taskAreaPoints, setTaskAreaPoints, taskAreaPointsRef] = useLiveState<LatLngPoint[]>([])
  const [taskPathPoints, setTaskPathPoints, taskPathPointsRef] = useLiveState<LatLngPoint[]>([])
  const [editingTaskId, setEditingTaskId, editingTaskIdRef] = useLiveState<number | null>(null)

  const [deviceId, setDeviceId] = useState('')
  const [name, setName] = useState('')
  const [robotEditName, setRobotEditName] = useState('')
  const [robotEditStatus, setRobotEditStatus] = useState('OFFLINE')
  const [taskLoading, setTaskLoading] = useState(false)
  const [taskSaving, setTaskSaving] = useState(false)
  const [taskActionMessage, setTaskActionMessage] = useState('')
  const [taskActionType, setTaskActionType] = useState<FeedbackType>('info')
  const [taskName, setTaskName] = useState('')
  const [taskStatus, setTaskStatus] = useState('PAUSED')
  const [taskAreaText, setTaskAreaText] = useState('')
  const [taskPathText, setTaskPathText] = useState('')
  const [robotResolvedAddress, setRobotResolvedAddress] = useState('')
  const [robotAddressLoading, setRobotAddressLoading] = useState(false)
  const [robotAddressError, setRobotAddressError] = useState('')

  // --- Map objects and bookkeeping ---
  const mapElRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const taskOverlayRef = useRef<L.LayerGroup | null>(null)
  const taskDraftOverlayRef = useRef<L.LayerGroup | null>(null)
  const markersRef = useRef(new Map<string, L.Marker>())
  const markerFramesRef = useRef(new Map<L.Marker, number>())
  const hasAutoFocusedRef = useRef(false)
  const mapInteractedRef = useRef(false)
  const lastOverlapWarningKeyRef = useRef('')
  const robotListLoadingRef = useRef(false)
  const robotListPendingRef = useRef(false)
  const addressCacheRef = useRef(new Map<string, string>())
  const addressKeyRef = useRef('')

  const selectedRobot = robots.find((item) => String(item.id) === String(selectedRobotId)) || null
  const selectedRobotAddressKey = addressKeyOf(selectedRobot)
  addressKeyRef.current = selectedRobotAddressKey

  function findSelectedRobot() {
    return robotsRef.current.find((item) => String(item.id) === String(selectedRobotIdRef.current)) || null
  }

  function setTaskActionFeedback(message: string, type: FeedbackType = 'info') {
    setTaskActionMessage(String(message || '').trim())
    setTaskActionType(type)
  }

  function syncRobotEditorFromSelected() {
    const robot = findSelectedRobot()
    if (!robot) return
    setRobotEditName(robot.name || '')
    setRobotEditStatus(robot.status || 'OFFLINE')
  }

  function setDraftArea(points: LatLngPoint[]) {
    setTaskAreaPoints(points)
    setTaskAreaText(formatCoordinateLines(points))
  }

  function setDraftPath(points: LatLngPoint[]) {
    setTaskPathPoints(points)
    setTaskPathText(formatCoordinateLines(points))
  }

  function resetTaskForm() {
    setEditingTaskId(null)
    setTaskName('')
    setTaskStatus('PAUSED')
    setTaskAreaText('')
    setTaskPathText('')
    setTaskAreaPoints([])
    setTaskPathPoints([])
    setTaskPickMode('none')
  }

  function warnIfInspectionAreasOverlap(tasks: PatrolTask[]) {
    const overlaps: string[] = []
    for (let i = 0; i < tasks.length; i += 1) {
      const areaA = normalizePointList(tasks[i]?.inspection_area || [])
      if (areaA.length < 3) continue
      for (let j = i + 1; j < tasks.length; j += 1) {
        const areaB = normalizePointList(tasks[j]?.inspection_area || [])
        if (areaB.length < 3) continue
        if (polygonsOverlap(areaA, areaB)) {
          overlaps.push(`${taskLabel(tasks[i])} 与 ${taskLabel(tasks[j])}`)
        }
      }
    }

    if (!overlaps.length) {
      lastOverlapWarningKeyRef.current = ''
      return
    }
    const warningKey = overlaps.join('|')
    if (warningKey === lastOverlapWarningKeyRef.current) return
    lastOverlapWarningKeyRef.current = warningKey

    const warningMessage = `检测区存在重合：${overlaps.join('；')}`
    setTaskActionFeedback(warningMessage, 'warning')
    pushFlash(warningMessage, 'warning')
    window.alert(warningMessage)
  }

  async function loadPatrolTasks(options: { silent?: boolean } = {}) {
    const silent = Boolean(options.silent)
    const robotId = selectedRobotIdRef.current
    if (!robotId) {
      setPatrolTasks([])
      lastOverlapWarningKeyRef.current = ''
      return
    }

    const previousStatusByTaskId = new Map(
      patrolTasksRef.current.map((task) => [Number(task.id), String(task.status || '').toUpperCase()]),
    )

    setTaskLoading(true)
    try {
      const payload = await getJson<{ tasks?: PatrolTask[] }>(`/api/robot/task/list?robot_id=${Number(robotId)}`)
      const tasks = payload.tasks || []
      setPatrolTasks(tasks)
      warnIfInspectionAreasOverlap(tasks)

      const newlyDoneTasks = tasks.filter((task) => {
        const currentStatus = String(task?.status || '').toUpperCase()
        return previousStatusByTaskId.get(Number(task?.id)) === 'RUNNING' && currentStatus === 'DONE'
      })
      if (newlyDoneTasks.length) {
        const successMessage = `巡检任务已完成：${newlyDoneTasks.map(taskLabel).join('、')}`
        setTaskActionFeedback(successMessage, 'success')
        pushFlash(successMessage, 'success')
      } else if (!silent) {
        setTaskActionFeedback(`已加载 ${tasks.length} 条巡检任务`, 'info')
      }
    } catch (error) {
      if (!silent) {
        setTaskActionFeedback(errorMessage(error, '巡检任务加载失败'), 'error')
      }
    } finally {
      setTaskLoading(false)
    }
  }

  function openEditor(robotId: number, mode: EditorMode) {
    setSelectedRobotId(String(robotId))
    setEditorMode(mode)
    setEditorVisible(true)
    syncRobotEditorFromSelected()
    if (mode === 'task') {
      resetTaskForm()
      loadPatrolTasks()
    }
  }

  function closeEditor() {
    setEditorVisible(false)
    setTaskPickMode('none')
  }

  function stopMarkerAnimation(marker: L.Marker) {
    const frame = markerFramesRef.current.get(marker)
    if (frame) {
      window.cancelAnimationFrame(frame)
      markerFramesRef.current.delete(marker)
    }
  }

  function animateMarkerTo(marker: L.Marker, nextLat: number, nextLng: number) {
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

    stopMarkerAnimation(marker)
    const startedAt = performance.now()
    const step = (now: number) => {
      const t = Math.min((now - startedAt) / MARKER_ANIMATION_MS, 1)
      const eased = t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2
      marker.setLatLng([startLat + deltaLat * eased, startLng + deltaLng * eased])
      if (t < 1) {
        markerFramesRef.current.set(marker, window.requestAnimationFrame(step))
      } else {
        markerFramesRef.current.delete(marker)
      }
    }
    markerFramesRef.current.set(marker, window.requestAnimationFrame(step))
  }

  function renderMarkers(robotList: Robot[]) {
    const map = mapRef.current
    if (!map) return
    const markers = markersRef.current
    const activeIds = new Set<string>()

    robotList.forEach((robot) => {
      if (robot.lat == null || robot.lng == null) return
      const markerId = String(robot.id)
      activeIds.add(markerId)
      const existing = markers.get(markerId)
      if (existing) {
        animateMarkerTo(existing, robot.lat, robot.lng)
        existing.setPopupContent(buildRobotPopup(robot))
        return
      }
      const marker = L.marker([robot.lat, robot.lng], {
        icon: L.divIcon({ className: 'map-dot-icon', html: '<span class="map-dot map-dot-robot"></span>', iconSize: [12, 12], iconAnchor: [6, 6] }),
      }).addTo(map).bindPopup(buildRobotPopup(robot))
      marker.on('click', () => {
        setSelectedRobotId(String(robot.id))
        syncRobotEditorFromSelected()
      })
      marker.on('contextmenu', (event: L.LeafletMouseEvent) => {
        event.originalEvent?.preventDefault()
        event.originalEvent?.stopPropagation()
        openEditor(robot.id, 'robot')
      })
      markers.set(markerId, marker)
    })

    markers.forEach((marker, markerId) => {
      if (activeIds.has(markerId)) return
      stopMarkerAnimation(marker)
      map.removeLayer(marker)
      markers.delete(markerId)
    })
  }

  async function loadRobots() {
    if (robotListLoadingRef.current) {
      robotListPendingRef.current = true
      return
    }
    robotListLoadingRef.current = true
    try {
      const payload = await getJson<{ robots?: Robot[] }>('/api/robot/live/list')
        .catch(() => getJson<{ robots?: Robot[] }>('/api/robot/list'))
      const sortedRobots = [...(payload.robots || [])].sort((a, b) => Number(b.id || 0) - Number(a.id || 0))
      setRobots(sortedRobots)

      if (!sortedRobots.length) {
        setSelectedRobotId(null)
        setPatrolTasks([])
        closeEditor()
      } else if (!sortedRobots.some((item) => String(item.id) === String(selectedRobotIdRef.current))) {
        setSelectedRobotId(String(sortedRobots[0].id))
      }

      renderMarkers(sortedRobots)

      if (!mapInteractedRef.current && !hasAutoFocusedRef.current) {
        const focusPoints = sortedRobots.map((item) => ({ lat: item.lat, lng: item.lng }))
        hasAutoFocusedRef.current = focusMapToDenseRegion(mapRef.current, focusPoints, { gridSize: 0.24, maxZoom: 16, singlePointZoom: 16 })
      }
    } catch (error) {
      pushFlash(errorMessage(error, '机器人列表加载失败'), 'error')
    } finally {
      robotListLoadingRef.current = false
      if (robotListPendingRef.current) {
        robotListPendingRef.current = false
        window.setTimeout(() => actionsRef.current.loadRobots(), 0)
      }
    }
  }

  function handleTaskMapClick(event: L.LeafletMouseEvent) {
    const pickMode = taskPickModeRef.current
    if (!editorVisibleRef.current || editorModeRef.current !== 'task' || pickMode === 'none') {
      return
    }
    const point = {
      lat: Number(event.latlng.lat.toFixed(6)),
      lng: Number(event.latlng.lng.toFixed(6)),
    }
    const current = pickMode === 'area' ? taskAreaPointsRef.current : taskPathPointsRef.current
    if (current.length >= MAP_PICK_POINT_LIMIT) {
      setTaskPickMode('none')
      return
    }
    const next = [...current, point]
    if (pickMode === 'area') {
      setDraftArea(next)
    } else {
      setDraftPath(next)
    }
    if (next.length >= MAP_PICK_POINT_LIMIT) setTaskPickMode('none')
  }

  async function navigateRobot(event: L.LeafletMouseEvent) {
    if (taskPickModeRef.current !== 'none') return
    const robotId = selectedRobotIdRef.current
    if (!robotId) return

    const latitude = event.latlng.lat
    const longitude = event.latlng.lng
    if (!window.confirm(`确认让设备 ${robotId} 导航到 (${latitude.toFixed(5)}, ${longitude.toFixed(5)}) ?`)) return

    try {
      await postJson('/api/robot/navigate', { id: Number(robotId), lat: latitude, lng: longitude })
      pushFlash('导航命令已发送', 'success')
    } catch (error) {
      pushFlash(errorMessage(error, '导航失败'), 'error')
    }
  }

  // Map handlers and timers are registered once; they call the latest functions through this ref.
  const actionsRef = useRef({ loadRobots, loadPatrolTasks, handleTaskMapClick, navigateRobot })
  actionsRef.current = { loadRobots, loadPatrolTasks, handleTaskMapClick, navigateRobot }

  // Create the map and start polling robots.
  useEffect(() => {
    const map = L.map(mapElRef.current!).setView([30, 110], 5)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(map)
    mapRef.current = map
    taskOverlayRef.current = L.layerGroup().addTo(map)
    taskDraftOverlayRef.current = L.layerGroup().addTo(map)

    map.on('click', (event: L.LeafletMouseEvent) => actionsRef.current.handleTaskMapClick(event))
    map.on('dblclick', (event: L.LeafletMouseEvent) => actionsRef.current.navigateRobot(event))
    map.on('dragstart zoomstart', () => {
      mapInteractedRef.current = true
    })

    actionsRef.current.loadRobots()
    const pollTimer = window.setInterval(() => actionsRef.current.loadRobots(), ROBOT_POLL_INTERVAL_MS)
    const onResize = () => map.invalidateSize()
    const sizeTimer = window.setTimeout(onResize, 300)
    window.addEventListener('resize', onResize)

    const markers = markersRef.current
    const frames = markerFramesRef.current
    return () => {
      window.clearInterval(pollTimer)
      window.clearTimeout(sizeTimer)
      window.removeEventListener('resize', onResize)
      frames.forEach((frame) => window.cancelAnimationFrame(frame))
      frames.clear()
      markers.clear()
      map.remove()
      mapRef.current = null
      taskOverlayRef.current = null
      taskDraftOverlayRef.current = null
      hasAutoFocusedRef.current = false
      mapInteractedRef.current = false
    }
  }, [])

  // When another robot is selected: refresh the editor fields and its patrol tasks.
  const previousSelectedRef = useRef(selectedRobotId)
  useEffect(() => {
    if (previousSelectedRef.current === selectedRobotId) return
    previousSelectedRef.current = selectedRobotId
    syncRobotEditorFromSelected()
    if (editorVisibleRef.current && editorModeRef.current === 'task') {
      resetTaskForm()
    }
    actionsRef.current.loadPatrolTasks()
  }, [selectedRobotId])

  // Switching the drawer to task mode starts with a fresh form.
  const previousModeRef = useRef(editorMode)
  useEffect(() => {
    if (previousModeRef.current === editorMode) return
    previousModeRef.current = editorMode
    if (editorVisibleRef.current && editorMode === 'task') {
      resetTaskForm()
      actionsRef.current.loadPatrolTasks()
    }
  }, [editorMode])

  // Poll patrol tasks while the task editor is open.
  useEffect(() => {
    if (!(editorVisible && editorMode === 'task' && selectedRobotId)) return
    actionsRef.current.loadPatrolTasks({ silent: true })
    const timer = window.setInterval(() => actionsRef.current.loadPatrolTasks({ silent: true }), TASK_POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [editorVisible, editorMode, selectedRobotId])

  // Resolve the selected robot's address while the drawer is open.
  useEffect(() => {
    if (!editorVisible) {
      setRobotAddressLoading(false)
      setRobotAddressError('')
      return
    }
    if (!selectedRobotAddressKey) return

    const cacheKey = selectedRobotAddressKey
    const [lat, lng] = cacheKey.split(',').map(Number)
    const cached = addressCacheRef.current.get(cacheKey)
    if (cached !== undefined) {
      setRobotResolvedAddress(cached)
      setRobotAddressError('')
      setRobotAddressLoading(false)
      return
    }

    setRobotAddressLoading(true)
    setRobotAddressError('')
    getJson<{ address?: string }>(`/api/robot/address?lat=${encodeURIComponent(lat)}&lng=${encodeURIComponent(lng)}`)
      .then((payload) => {
        const rawAddress = String(payload.address || '').trim()
        const address = (/^not\s*found$/i.test(rawAddress) ? '' : rawAddress) || '未解析到详细地址'
        addressCacheRef.current.set(cacheKey, address)
        if (addressKeyRef.current === cacheKey) {
          setRobotResolvedAddress(address)
        }
      })
      .catch((error) => {
        if (addressKeyRef.current === cacheKey) {
          setRobotResolvedAddress(`坐标：${lat.toFixed(5)}, ${lng.toFixed(5)}`)
          setRobotAddressError(errorMessage(error, '地址解析失败'))
        }
      })
      .finally(() => {
        if (addressKeyRef.current === cacheKey) {
          setRobotAddressLoading(false)
        }
      })
  }, [selectedRobotAddressKey, editorVisible])

  // A selected robot without coordinates has no address to resolve.
  useEffect(() => {
    if (editorVisible && selectedRobot && !selectedRobotAddressKey) {
      setRobotResolvedAddress('暂无定位信息')
      setRobotAddressError('')
      setRobotAddressLoading(false)
    }
  }, [editorVisible, selectedRobot, selectedRobotAddressKey])

  // Draw the task being edited (draft points, area polygon, path line).
  useEffect(() => {
    const layer = taskDraftOverlayRef.current
    if (!layer) return
    layer.clearLayers()

    taskAreaPoints.forEach((point) => {
      L.circleMarker([point.lat, point.lng], { radius: 5, color: '#d53f50', weight: 2, fillColor: '#ef7483', fillOpacity: 0.85 }).addTo(layer)
    })
    const areaLatLngs = taskAreaPoints.map((point) => [point.lat, point.lng] as [number, number])
    if (taskAreaPoints.length >= 3) {
      L.polygon(areaLatLngs, { color: '#d53f50', weight: 2, fillColor: '#ef7483', fillOpacity: 0.18 }).addTo(layer)
    } else if (taskAreaPoints.length >= 2) {
      L.polyline(areaLatLngs, { color: '#d53f50', weight: 2 }).addTo(layer)
    }

    taskPathPoints.forEach((point) => {
      L.circleMarker([point.lat, point.lng], { radius: 5, color: '#2563eb', weight: 2, fillColor: '#60a5fa', fillOpacity: 0.85 }).addTo(layer)
    })
    if (taskPathPoints.length >= 2) {
      L.polyline(taskPathPoints.map((point) => [point.lat, point.lng] as [number, number]), { color: '#2563eb', weight: 3, dashArray: '6 6' }).addTo(layer)
    }
  }, [taskAreaPoints, taskPathPoints])

  // Draw the saved patrol tasks of the selected robot.
  useEffect(() => {
    const layer = taskOverlayRef.current
    if (!layer) return
    layer.clearLayers()

    patrolTasks.forEach((task) => {
      const areaPoints = normalizePointList(task.inspection_area || [])
      const pathPoints = normalizePointList(task.planned_path || [])
      const isRunning = String(task.status || '').toUpperCase() === 'RUNNING'
      const areaColor = isRunning ? '#f97316' : '#d53f50'
      const areaFillColor = isRunning ? '#fdba74' : '#ef7483'
      const pathColor = isRunning ? '#0f766e' : '#2563eb'
      const label = task.name || `任务 #${task.id}`

      areaPoints.forEach((point) => {
        L.circleMarker([point.lat, point.lng], { radius: 4, color: areaColor, weight: 1.5, fillColor: areaFillColor, fillOpacity: 0.72 })
          .bindTooltip(label).addTo(layer)
      })
      if (areaPoints.length >= 3) {
        L.polygon(areaPoints.map((point) => [point.lat, point.lng] as [number, number]), {
          color: areaColor, weight: 2, fillColor: areaFillColor, fillOpacity: 0.14,
        }).bindTooltip(`${label} 检测区`).addTo(layer)
      }

      pathPoints.forEach((point) => {
        L.circleMarker([point.lat, point.lng], { radius: 4, color: pathColor, weight: 1.5, fillColor: '#60a5fa', fillOpacity: 0.72 })
          .bindTooltip(label).addTo(layer)
      })
      if (pathPoints.length >= 2) {
        L.polyline(pathPoints.map((point) => [point.lat, point.lng] as [number, number]), {
          color: pathColor, weight: 2.5, dashArray: '6 6', opacity: 0.88,
        }).bindTooltip(`${label} 路径`).addTo(layer)
      }
    })
  }, [patrolTasks])

  // --- UI actions ---

  function startTaskPickMode(mode: 'area' | 'path') {
    if (!selectedRobotIdRef.current) {
      pushFlash('请先右键选择一个机器人', 'warning')
      return
    }
    setTaskPickMode(mode)
    setTaskActionFeedback(`已开启${mode === 'area' ? '巡检区域' : '路径规划'}选四点模式，请点击地图`, 'info')
  }

  async function addRobot() {
    try {
      const payload = await postJson('/api/robot/register', { device_id: deviceId.trim(), name: name.trim() })
      if (!payload.ok) {
        throw new Error(payload.msg || '添加失败')
      }
      setDeviceId('')
      setName('')
      await loadRobots()
      pushFlash('机器人添加成功', 'success')
    } catch (error) {
      pushFlash(errorMessage(error, '添加失败'), 'error')
    }
  }

  async function saveRobotProfile() {
    const robot = findSelectedRobot()
    if (!robot) {
      pushFlash('请先选择机器人', 'warning')
      return
    }
    const newName = robotEditName.trim()
    if (!newName) {
      pushFlash('机器人名称不能为空', 'warning')
      return
    }
    try {
      await postJson('/api/robot/update', { id: Number(robot.id), name: newName, status: robotEditStatus })
      await loadRobots()
      pushFlash('机器人信息已更新', 'success')
    } catch (error) {
      pushFlash(errorMessage(error, '机器人信息更新失败'), 'error')
    }
  }

  async function deleteRobot(robotId: number) {
    if (!window.confirm('确认删除该机器人？')) return
    try {
      await postJson(`/api/robot/delete/${robotId}`, {})
      if (String(selectedRobotIdRef.current) === String(robotId)) {
        setSelectedRobotId(null)
        closeEditor()
      }
      await loadRobots()
      pushFlash('机器人已删除', 'success')
    } catch (error) {
      pushFlash(errorMessage(error, '删除失败'), 'error')
    }
  }

  async function loadTaskDetail(taskId: number) {
    try {
      const payload = await getJson<{ task?: PatrolTask | null }>(`/api/robot/task/${taskId}`)
      const task = payload.task || null
      if (!task) throw new Error('任务不存在')

      setEditingTaskId(task.id)
      setTaskName(task.name || '')
      setTaskStatus(task.status || 'PLANNED')
      setDraftArea(normalizePointList(task.inspection_area || []))
      setDraftPath(normalizePointList(task.planned_path || []))
      setTaskPickMode('none')
      setTaskActionFeedback(`已加载任务 #${task.id}`, 'info')
    } catch (error) {
      setTaskActionFeedback(errorMessage(error, '任务详情加载失败'), 'error')
    }
  }

  async function savePatrolTask() {
    const robotId = selectedRobotIdRef.current
    if (!robotId) {
      setTaskActionFeedback('请先选择机器人', 'warning')
      return
    }

    let geometry: { area: LatLngPoint[]; path: LatLngPoint[] }
    try {
      geometry = parseTaskGeometry(taskAreaText, taskPathText)
    } catch (error) {
      setTaskActionFeedback(errorMessage(error, '任务坐标格式错误'), 'error')
      return
    }

    const payload = {
      name: taskName.trim(),
      inspection_area: geometry.area,
      planned_path: geometry.path,
      status: taskStatus,
    }
    if (!payload.name) {
      setTaskActionFeedback('任务名称不能为空', 'warning')
      return
    }

    setTaskSaving(true)
    const editingId = editingTaskIdRef.current
    setTaskActionFeedback(editingId ? '正在更新巡检任务...' : '正在创建巡检任务...', 'info')
    try {
      if (editingId) {
        const updateResp = await postJson<{ task?: PatrolTask }>(`/api/robot/task/update/${editingId}`, payload)
        if (updateResp.task?.id) setEditingTaskId(updateResp.task.id)
        setTaskActionFeedback('巡检任务已更新', 'success')
      } else {
        const createResp = await postJson<{ task?: PatrolTask }>('/api/robot/task/create', { robot_id: Number(robotId), ...payload })
        if (createResp.task?.id) setEditingTaskId(createResp.task.id)
        setTaskActionFeedback('巡检任务已创建', 'success')
      }
      setTaskAreaPoints(normalizePointList(geometry.area))
      setTaskPathPoints(normalizePointList(geometry.path))
      setTaskPickMode('none')
      await loadPatrolTasks()
    } catch (error) {
      setTaskActionFeedback(errorMessage(error, '巡检任务保存失败'), 'error')
    } finally {
      setTaskSaving(false)
    }
  }

  async function updateTaskStatus(taskId: number, status: string) {
    try {
      await postJson(`/api/robot/task/update/${taskId}`, { status })
      await loadPatrolTasks()
    } catch (error) {
      setTaskActionFeedback(errorMessage(error, '任务状态更新失败'), 'error')
    }
  }

  async function deletePatrolTask(taskId: number) {
    if (!window.confirm('确认删除该巡检任务？')) return
    try {
      await postJson(`/api/robot/task/delete/${taskId}`, {})
      if (Number(editingTaskIdRef.current) === Number(taskId)) resetTaskForm()
      await loadPatrolTasks()
      setTaskActionFeedback('巡检任务已删除', 'success')
    } catch (error) {
      setTaskActionFeedback(errorMessage(error, '巡检任务删除失败'), 'error')
    }
  }

  const taskPickModeLabel = taskPickMode === 'area' ? '巡检区域' : taskPickMode === 'path' ? '路径规划' : '未开启'

  return (
    <div className="scope-robot-admin robot-admin-page">
      <div className="map-toolbar">
        <div className="toolbar-title">机器人任务部署</div>
        <div className="toolbar-row">
          <input value={deviceId} onChange={(event) => setDeviceId(event.target.value)} className="input-control toolbar-input" placeholder="设备ID" />
          <input value={name} onChange={(event) => setName(event.target.value)} className="input-control toolbar-input" placeholder="名称" />
          <button type="button" className="square-btn" onClick={addRobot}>添加机器人</button>
          <button type="button" className="square-btn" onClick={() => loadRobots()}>刷新</button>
        </div>
        <div className="toolbar-sub">双击地图可向当前选中机器人下发导航；右键机器人点直接打开详情管理面板。</div>
      </div>

      <div id="robotMap" ref={mapElRef} className="robot-map-full"></div>

      {editorVisible && selectedRobot && (
        <div className="editor-drawer">
          <div className="drawer-head">
            <div className="drawer-identity">
              <div className="drawer-title">{selectedRobot.name || '-'} #{selectedRobot.id}</div>
              <div className="drawer-subtitle">设备ID：{selectedRobot.device_id || '-'}</div>
              <div className="drawer-meta-row">
                <span className={`status-chip ${statusClass(selectedRobot.status)}`}>{selectedRobot.status || 'UNKNOWN'}</span>
                <span className="meta-chip">电量 {selectedRobot.battery ?? '-'}%</span>
              </div>
            </div>
            <button type="button" className="square-btn btn-ghost" onClick={closeEditor}>关闭</button>
          </div>

          <div className="drawer-mode-switch">
            <button
              type="button"
              className={`square-btn${editorMode === 'robot' ? ' square-btn-active' : ''}`}
              onClick={() => setEditorMode('robot')}
            >
              机器人管理
            </button>
            <button
              type="button"
              className={`square-btn${editorMode === 'task' ? ' square-btn-active' : ''}`}
              onClick={() => setEditorMode('task')}
            >
              巡检任务管理
            </button>
          </div>

          {editorMode === 'robot' && (
            <div className="drawer-body">
              <div className="robot-quick-grid">
                <div className="quick-card">
                  <div className="quick-label">在线状态</div>
                  <div className={`quick-value ${statusClass(selectedRobot.status)}`}>{selectedRobot.status || 'UNKNOWN'}</div>
                </div>
                <div className="quick-card quick-card-wide">
                  <div className="quick-label">当前位置</div>
                  <div className="quick-value quick-address-value">
                    {robotAddressLoading ? '地址解析中...' : robotResolvedAddress || '暂无定位信息'}
                  </div>
                  {robotAddressError && <div className="quick-subvalue">{robotAddressError}</div>}
                </div>
              </div>

              <input value={robotEditName} onChange={(event) => setRobotEditName(event.target.value)} className="input-control" placeholder="机器人名称" />
              <select value={robotEditStatus} onChange={(event) => setRobotEditStatus(event.target.value)} className="input-control">
                {ROBOT_STATUSES.map((status) => (
                  <option key={status} value={status}>{status}</option>
                ))}
              </select>
              <div className="drawer-actions robot-actions">
                <button type="button" className="square-btn robot-action-btn" onClick={saveRobotProfile}>保存机器人</button>
                <button type="button" className="square-btn btn-delete robot-action-btn" onClick={() => deleteRobot(selectedRobot.id)}>删除机器人</button>
                <Link className="square-btn robot-action-btn" to={`/robot/${selectedRobot.id}`}>手动控制</Link>
              </div>
            </div>
          )}

          {editorMode === 'task' && (
            <div className="drawer-body task-drawer-body">
              <div className="task-map-tools">
                <button
                  type="button"
                  className={`square-btn${taskPickMode === 'area' ? ' square-btn-active' : ''}`}
                  onClick={() => startTaskPickMode('area')}
                >
                  地图选四点-区域
                </button>
                <button
                  type="button"
                  className={`square-btn${taskPickMode === 'path' ? ' square-btn-active' : ''}`}
                  onClick={() => startTaskPickMode('path')}
                >
                  地图选四点-路径
                </button>
                <button type="button" className="square-btn" onClick={() => setTaskPickMode('none')}>停止选点</button>
              </div>

              <div className="task-map-hint">
                模式：{taskPickModeLabel} ｜ 区域 {taskAreaPoints.length}/{MAP_PICK_POINT_LIMIT} ｜ 路径 {taskPathPoints.length}/{MAP_PICK_POINT_LIMIT}
              </div>

              <input value={taskName} onChange={(event) => setTaskName(event.target.value)} className="input-control" placeholder="任务名称，例如：校园北区早巡" />
              <select value={taskStatus} onChange={(event) => setTaskStatus(event.target.value)} className="input-control">
                {PATROL_STATUSES.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>

              <div className="task-textarea-head">
                <span>巡检区域坐标（固定 4 点）</span>
                <button type="button" className="square-btn" onClick={() => setDraftArea([])}>清空区域</button>
              </div>
              <textarea
                value={taskAreaText}
                onChange={(event) => setTaskAreaText(event.target.value)}
                className="input-control task-textarea"
                placeholder={AREA_PLACEHOLDER}
              />

              <div className="task-textarea-head">
                <span>规划路径坐标（为空或固定 4 点）</span>
                <button type="button" className="square-btn" onClick={() => setDraftPath([])}>清空路径</button>
              </div>
              <textarea
                value={taskPathText}
                onChange={(event) => setTaskPathText(event.target.value)}
                className="input-control task-textarea"
                placeholder={PATH_PLACEHOLDER}
              />

              <div className="drawer-actions">
                <button type="button" className="square-btn" disabled={taskSaving} onClick={savePatrolTask}>
                  {taskSaving ? '提交中...' : editingTaskId ? '保存更新' : '新建任务'}
                </button>
                <button type="button" className="square-btn" onClick={resetTaskForm}>重置</button>
              </div>

              {taskActionMessage && (
                <div className={`task-action-feedback task-action-${taskActionType}`}>{taskActionMessage}</div>
              )}
              {editingTaskId && <div className="task-editing-tip">当前编辑任务 #{editingTaskId}</div>}

              <div className="task-list-wrap">
                {taskLoading ? (
                  <div className="empty-state">任务载入中...</div>
                ) : (
                  <>
                    {patrolTasks.map((task) => (
                      <div key={task.id} className="task-list-item">
                        <div className="task-item-head">
                          <span className="task-item-name">{task.name}</span>
                          <span className={`task-item-status ${statusClass(task.status)}`}>{task.status}</span>
                        </div>
                        <div className="task-item-meta">创建时间：{task.created_at || '-'}</div>
                        <div className="task-item-actions">
                          <button type="button" className="square-btn" onClick={() => loadTaskDetail(task.id)}>编辑</button>
                          <button type="button" className="square-btn" onClick={() => updateTaskStatus(task.id, 'RUNNING')}>运行</button>
                          <button type="button" className="square-btn" onClick={() => updateTaskStatus(task.id, 'PAUSED')}>暂停</button>
                          <button type="button" className="square-btn" onClick={() => updateTaskStatus(task.id, 'DONE')}>完成</button>
                          <button type="button" className="square-btn btn-delete" onClick={() => deletePatrolTask(task.id)}>删除</button>
                        </div>
                      </div>
                    ))}
                    {!patrolTasks.length && <div className="empty-state">暂无巡检任务</div>}
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
