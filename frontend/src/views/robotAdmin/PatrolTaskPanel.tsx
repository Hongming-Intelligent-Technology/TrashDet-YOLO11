import { MAP_PICK_POINT_LIMIT } from '../../lib/patrolGeometry'
import { PATROL_STATUSES, statusClass, type FeedbackType, type PatrolTask, type PickMode } from './shared'

const AREA_PLACEHOLDER = '每行一个点：\n30.123456,120.123456\n30.223456,120.223456\n30.323456,120.323456\n30.423456,120.423456'
const PATH_PLACEHOLDER = '每行一个点：\n30.120000,120.120000\n30.220000,120.220000\n30.320000,120.320000\n30.420000,120.420000'

const PICK_MODE_LABELS: Record<PickMode, string> = { area: '巡检区域', path: '路径规划', none: '未开启' }

export interface TaskForm {
  name: string
  status: string
  areaText: string
  pathText: string
}

interface Props {
  form: TaskForm
  onFormChange: (patch: Partial<TaskForm>) => void
  pickMode: PickMode
  onStartPick: (mode: 'area' | 'path') => void
  onStopPick: () => void
  areaPointCount: number
  pathPointCount: number
  onClearArea: () => void
  onClearPath: () => void
  editingTaskId: number | null
  saving: boolean
  onSave: () => void
  onReset: () => void
  feedback: { message: string; type: FeedbackType }
  loading: boolean
  tasks: PatrolTask[]
  onEditTask: (taskId: number) => void
  onSetTaskStatus: (taskId: number, status: string) => void
  onDeleteTask: (taskId: number) => void
}

/** "巡检任务管理" tab of the editor drawer: task form, map point picking and the task list. */
export default function PatrolTaskPanel({
  form,
  onFormChange,
  pickMode,
  onStartPick,
  onStopPick,
  areaPointCount,
  pathPointCount,
  onClearArea,
  onClearPath,
  editingTaskId,
  saving,
  onSave,
  onReset,
  feedback,
  loading,
  tasks,
  onEditTask,
  onSetTaskStatus,
  onDeleteTask,
}: Props) {
  return (
    <div className="drawer-body task-drawer-body">
      <div className="task-map-tools">
        <button
          type="button"
          className={`square-btn${pickMode === 'area' ? ' square-btn-active' : ''}`}
          onClick={() => onStartPick('area')}
        >
          地图选四点-区域
        </button>
        <button
          type="button"
          className={`square-btn${pickMode === 'path' ? ' square-btn-active' : ''}`}
          onClick={() => onStartPick('path')}
        >
          地图选四点-路径
        </button>
        <button type="button" className="square-btn" onClick={onStopPick}>停止选点</button>
      </div>

      <div className="task-map-hint">
        模式：{PICK_MODE_LABELS[pickMode]} ｜ 区域 {areaPointCount}/{MAP_PICK_POINT_LIMIT} ｜ 路径 {pathPointCount}/{MAP_PICK_POINT_LIMIT}
      </div>

      <input value={form.name} onChange={(event) => onFormChange({ name: event.target.value })} className="input-control" placeholder="任务名称，例如：校园北区早巡" />
      <select value={form.status} onChange={(event) => onFormChange({ status: event.target.value })} className="input-control">
        {PATROL_STATUSES.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </select>

      <div className="task-textarea-head">
        <span>巡检区域坐标（固定 4 点）</span>
        <button type="button" className="square-btn" onClick={onClearArea}>清空区域</button>
      </div>
      <textarea
        value={form.areaText}
        onChange={(event) => onFormChange({ areaText: event.target.value })}
        className="input-control task-textarea"
        placeholder={AREA_PLACEHOLDER}
      />

      <div className="task-textarea-head">
        <span>规划路径坐标（为空或固定 4 点）</span>
        <button type="button" className="square-btn" onClick={onClearPath}>清空路径</button>
      </div>
      <textarea
        value={form.pathText}
        onChange={(event) => onFormChange({ pathText: event.target.value })}
        className="input-control task-textarea"
        placeholder={PATH_PLACEHOLDER}
      />

      <div className="drawer-actions">
        <button type="button" className="square-btn" disabled={saving} onClick={onSave}>
          {saving ? '提交中...' : editingTaskId ? '保存更新' : '新建任务'}
        </button>
        <button type="button" className="square-btn" onClick={onReset}>重置</button>
      </div>

      {feedback.message && (
        <div className={`task-action-feedback task-action-${feedback.type}`}>{feedback.message}</div>
      )}
      {editingTaskId && <div className="task-editing-tip">当前编辑任务 #{editingTaskId}</div>}

      <div className="task-list-wrap">
        {loading ? (
          <div className="empty-state">任务载入中...</div>
        ) : (
          <>
            {tasks.map((task) => (
              <div key={task.id} className="task-list-item">
                <div className="task-item-head">
                  <span className="task-item-name">{task.name}</span>
                  <span className={`task-item-status ${statusClass(task.status)}`}>{task.status}</span>
                </div>
                <div className="task-item-meta">创建时间：{task.created_at || '-'}</div>
                <div className="task-item-actions">
                  <button type="button" className="square-btn" onClick={() => onEditTask(task.id)}>编辑</button>
                  <button type="button" className="square-btn" onClick={() => onSetTaskStatus(task.id, 'RUNNING')}>运行</button>
                  <button type="button" className="square-btn" onClick={() => onSetTaskStatus(task.id, 'PAUSED')}>暂停</button>
                  <button type="button" className="square-btn" onClick={() => onSetTaskStatus(task.id, 'DONE')}>完成</button>
                  <button type="button" className="square-btn btn-delete" onClick={() => onDeleteTask(task.id)}>删除</button>
                </div>
              </div>
            ))}
            {!tasks.length && <div className="empty-state">暂无巡检任务</div>}
          </>
        )}
      </div>
    </div>
  )
}
