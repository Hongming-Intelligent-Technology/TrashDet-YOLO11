/** Types, constants and small helpers shared by the robot admin page and its panels. */
import { escapeHtml } from '../../lib/escape'
import { normalizePointList, polygonsOverlap, type LatLngPoint } from '../../lib/patrolGeometry'

export interface Robot {
  id: number
  device_id?: string | null
  name?: string | null
  status?: string | null
  battery?: number | null
  lat?: number | null
  lng?: number | null
}

export interface PatrolTask {
  id: number
  name?: string | null
  status?: string | null
  inspection_area?: LatLngPoint[]
  planned_path?: LatLngPoint[]
  created_at?: string | null
}

export type EditorMode = 'robot' | 'task'
export type PickMode = 'none' | 'area' | 'path'
export type FeedbackType = 'info' | 'success' | 'warning' | 'error'

export const ROBOT_STATUSES = ['ONLINE', 'OFFLINE', 'PAUSED', 'ERROR']
export const PATROL_STATUSES = [
  { value: 'PLANNED', label: '待执行' },
  { value: 'RUNNING', label: '执行中' },
  { value: 'PAUSED', label: '已暂停' },
  { value: 'DONE', label: '已完成' },
  { value: 'CANCELLED', label: '已取消' },
]

/** CSS class for a status value, e.g. "ONLINE" -> "status-online". */
export function statusClass(status?: string | null) {
  const token = String(status || 'unknown')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, '-')
  return `status-${token || 'unknown'}`
}

export function buildRobotPopup(robot: Robot) {
  return `<b>${escapeHtml(robot.name || '-')}</b><br>${escapeHtml(robot.device_id || '-')}`
}

/** Rounded "lat,lng" key used to cache address lookups; empty when the robot has no position. */
export function addressKeyOf(robot: Robot | null) {
  if (!robot) return ''
  const lat = Number(robot.lat)
  const lng = Number(robot.lng)
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return ''
  return `${lat.toFixed(5)},${lng.toFixed(5)}`
}

export function taskLabel(task: PatrolTask | undefined) {
  return task?.name || `任务#${task?.id}`
}

/** Human-readable "A 与 B" pairs of tasks whose inspection areas overlap. */
export function findOverlappingAreas(tasks: PatrolTask[]): string[] {
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
  return overlaps
}
