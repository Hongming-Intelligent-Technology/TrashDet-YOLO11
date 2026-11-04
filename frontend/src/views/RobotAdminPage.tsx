import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import { useLiveState } from '../hooks/useLiveState'
import { errorMessage, getJson, postJson } from '../lib/api'
import { focusMapToDenseRegion } from '../lib/mapFocus'
import {
  MAP_PICK_POINT_LIMIT,
  formatCoordinateLines,
  normalizePointList,
  parseTaskGeometry,
  type LatLngPoint,
} from '../lib/patrolGeometry'
import { pollWhileVisible } from '../lib/polling'
import { pushFlash } from '../stores/session'
import { animateMarkerTo, drawDraftTask, drawPatrolTasks, stopMarkerAnimation } from './robotAdmin/mapLayers'
import PatrolTaskPanel, { type TaskForm } from './robotAdmin/PatrolTaskPanel'
import RobotProfilePanel from './robotAdmin/RobotProfilePanel'
import {
  buildRobotPopup,
  findOverlappingAreas,
  statusClass,
  taskLabel,
  type EditorMode,
  type FeedbackType,
  type PatrolTask,
  type PickMode,
  type Robot,
} from './robotAdmin/shared'
import { useRobotAddress } from './robotAdmin/useRobotAddress'
import './RobotAdminPage.css'

const ROBOT_POLL_INTERVAL_MS = 500
const TASK_POLL_INTERVAL_MS = 1000

const EMPTY_TASK_FORM: TaskForm = { name: '', status: 'PAUSED', areaText: '', pathText: '' }

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
  const [taskForm, setTaskForm] = useState<TaskForm>(EMPTY_TASK_FORM)
  const [taskLoading, setTaskLoading] = useState(false)
  const [taskSaving, setTaskSaving] = useState(false)
  const [taskFeedback, setTaskFeedback] = useState<{ message: string; type: FeedbackType }>({ message: '', type: 'info' })

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

  const selectedRobot = robots.find((item) => String(item.id) === String(selectedRobotId)) || null
  const robotAddress = useRobotAddress(selectedRobot, editorVisible)

  function findSelectedRobot() {
    return robotsRef.current.find((item) => String(item.id) === String(selectedRobotIdRef.current)) || null
  }

  function setTaskActionFeedback(message: string, type: FeedbackType = 'info') {
    setTaskFeedback({ message: String(message || '').trim(), type })
  }

  function syncRobotEditorFromSelected() {
    const robot = findSelectedRobot()
    if (!robot) return
    setRobotEditName(robot.name || '')
    setRobotEditStatus(robot.status || 'OFFLINE')
  }

  function patchTaskForm(patch: Partial<TaskForm>) {
    setTaskForm((form) => ({ ...form, ...patch }))
  }

  function setDraftArea(points: LatLngPoint[]) {
    setTaskAreaPoints(points)
    patchTaskForm({ areaText: formatCoordinateLines(points) })
  }

  function setDraftPath(points: LatLngPoint[]) {
    setTaskPathPoints(points)
    patchTaskForm({ pathText: formatCoordinateLines(points) })
  }

  function resetTaskForm() {
    setEditingTaskId(null)
    setTaskForm(EMPTY_TASK_FORM)
    setTaskAreaPoints([])
    setTaskPathPoints([])
    setTaskPickMode('none')
  }

  function warnIfInspectionAreasOverlap(tasks: PatrolTask[]) {
    const overlaps = findOverlappingAreas(tasks)
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

  function renderMarkers(robotList: Robot[]) {
    const map = mapRef.current
    if (!map) return
    const markers = markersRef.current
    const frames = markerFramesRef.current
    const activeIds = new Set<string>()

    robotList.forEach((robot) => {
      if (robot.lat == null || robot.lng == null) return
      const markerId = String(robot.id)
      activeIds.add(markerId)
      const existing = markers.get(markerId)
      if (existing) {
        animateMarkerTo(existing, robot.lat, robot.lng, frames)
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
      stopMarkerAnimation(marker, frames)
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

  // When another robot is selected: refresh the editor fields and its patrol tasks.
  function onSelectedRobotChanged() {
    syncRobotEditorFromSelected()
    if (editorVisibleRef.current && editorModeRef.current === 'task') {
      resetTaskForm()
    }
    loadPatrolTasks()
  }

  // Switching the drawer to task mode starts with a fresh form.
  function onEditorModeChanged() {
    if (editorVisibleRef.current && editorModeRef.current === 'task') {
      resetTaskForm()
      loadPatrolTasks()
    }
  }

  // Map handlers, timers and change effects run once or on specific changes; they call the
  // latest version of these functions through this ref.
  const actions = { loadRobots, loadPatrolTasks, handleTaskMapClick, navigateRobot, onSelectedRobotChanged, onEditorModeChanged }
  const actionsRef = useRef(actions)
  actionsRef.current = actions

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

    const stopPolling = pollWhileVisible(() => actionsRef.current.loadRobots(), ROBOT_POLL_INTERVAL_MS)
    const onResize = () => map.invalidateSize()
    const sizeTimer = window.setTimeout(onResize, 300)
    window.addEventListener('resize', onResize)

    const markers = markersRef.current
    const frames = markerFramesRef.current
    return () => {
      stopPolling()
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

  const previousSelectedRef = useRef(selectedRobotId)
  useEffect(() => {
    if (previousSelectedRef.current === selectedRobotId) return
    previousSelectedRef.current = selectedRobotId
    actionsRef.current.onSelectedRobotChanged()
  }, [selectedRobotId])

  const previousModeRef = useRef(editorMode)
  useEffect(() => {
    if (previousModeRef.current === editorMode) return
    previousModeRef.current = editorMode
    actionsRef.current.onEditorModeChanged()
  }, [editorMode])

  // Poll patrol tasks while the task editor is open.
  useEffect(() => {
    if (!(editorVisible && editorMode === 'task' && selectedRobotId)) return
    return pollWhileVisible(() => actionsRef.current.loadPatrolTasks({ silent: true }), TASK_POLL_INTERVAL_MS)
  }, [editorVisible, editorMode, selectedRobotId])

  useEffect(() => {
    if (taskDraftOverlayRef.current) drawDraftTask(taskDraftOverlayRef.current, taskAreaPoints, taskPathPoints)
  }, [taskAreaPoints, taskPathPoints])

  useEffect(() => {
    if (taskOverlayRef.current) drawPatrolTasks(taskOverlayRef.current, patrolTasks)
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
      patchTaskForm({ name: task.name || '', status: task.status || 'PLANNED' })
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
      geometry = parseTaskGeometry(taskForm.areaText, taskForm.pathText)
    } catch (error) {
      setTaskActionFeedback(errorMessage(error, '任务坐标格式错误'), 'error')
      return
    }

    const payload = {
      name: taskForm.name.trim(),
      inspection_area: geometry.area,
      planned_path: geometry.path,
      status: taskForm.status,
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
            <RobotProfilePanel
              robot={selectedRobot}
              address={robotAddress}
              editName={robotEditName}
              editStatus={robotEditStatus}
              onEditNameChange={setRobotEditName}
              onEditStatusChange={setRobotEditStatus}
              onSave={saveRobotProfile}
              onDelete={() => deleteRobot(selectedRobot.id)}
            />
          )}

          {editorMode === 'task' && (
            <PatrolTaskPanel
              form={taskForm}
              onFormChange={patchTaskForm}
              pickMode={taskPickMode}
              onStartPick={startTaskPickMode}
              onStopPick={() => setTaskPickMode('none')}
              areaPointCount={taskAreaPoints.length}
              pathPointCount={taskPathPoints.length}
              onClearArea={() => setDraftArea([])}
              onClearPath={() => setDraftPath([])}
              editingTaskId={editingTaskId}
              saving={taskSaving}
              onSave={savePatrolTask}
              onReset={resetTaskForm}
              feedback={taskFeedback}
              loading={taskLoading}
              tasks={patrolTasks}
              onEditTask={loadTaskDetail}
              onSetTaskStatus={updateTaskStatus}
              onDeleteTask={deletePatrolTask}
            />
          )}
        </div>
      )}
    </div>
  )
}
