import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { errorMessage, getJson, postJson } from '../../lib/api'
import { fieldUpdater } from '../../lib/forms'
import { pushFlash, setSessionUser, type SessionUser } from '../../stores/session'
import { EMPTY_PROFILE_FORM, profileFormFrom, profilePayload, type ProfileForm, type UserRow } from './shared'

interface OwnedRobot {
  id: number
  name?: string | null
  device_id?: string | null
  status?: string | null
}

interface OwnedPatrolTask {
  id: number
  name?: string | null
  status?: string | null
  robot_id?: number
  created_at?: string | null
}

const PATROL_STATUS_TEXT: Record<string, string> = {
  PLANNED: '待执行',
  RUNNING: '执行中',
  PAUSED: '已暂停',
  DONE: '已完成',
  CANCELLED: '已取消',
}

function patrolStatusText(status?: string | null) {
  return PATROL_STATUS_TEXT[String(status || '').toUpperCase()] || status || '-'
}

function byIdDesc<T extends { id?: number }>(a: T, b: T) {
  return Number(b.id || 0) - Number(a.id || 0)
}

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return String(value)
  return dt.toLocaleString('zh-CN', { hour12: false })
}

interface Props {
  /** The logged-in user's row, or null when the backend returned none. */
  ownRow: UserRow | null
  currentUsername: string
  currentRoleText: string
  /** Increments each time the parent loads the user data; resets the form and reloads robots/tasks. */
  loadVersion: number
  /** Reload the page's user data after a change. */
  onChanged: () => Promise<void>
}

/** Regular-user view: edit your own profile and manage your own robots and patrol tasks. */
export default function SelfProfileSection({ ownRow, currentUsername, currentRoleText, loadVersion, onChanged }: Props) {
  const [selfForm, setSelfForm] = useState<ProfileForm>(EMPTY_PROFILE_FORM)
  const [selfSubmitting, setSelfSubmitting] = useState(false)
  const [myRobots, setMyRobots] = useState<OwnedRobot[]>([])
  const [myPatrolTasks, setMyPatrolTasks] = useState<OwnedPatrolTask[]>([])
  const [assetsLoading, setAssetsLoading] = useState(false)
  const [robotOpsLoadingId, setRobotOpsLoadingId] = useState<number | null>(null)
  const [patrolOpsLoadingId, setPatrolOpsLoadingId] = useState<number | null>(null)
  const updateSelf = fieldUpdater(setSelfForm)

  const loadAssets = useCallback(async () => {
    setAssetsLoading(true)
    try {
      const [robotPayload, taskPayload] = await Promise.all([
        getJson<{ robots?: OwnedRobot[] }>('/api/robot/list'),
        getJson<{ tasks?: OwnedPatrolTask[] }>('/api/robot/task/list'),
      ])
      setMyRobots([...(robotPayload.robots || [])].sort(byIdDesc))
      setMyPatrolTasks([...(taskPayload.tasks || [])].sort(byIdDesc))
    } catch (error) {
      setMyRobots([])
      setMyPatrolTasks([])
      pushFlash(errorMessage(error, '加载个人资产失败'), 'error')
    } finally {
      setAssetsLoading(false)
    }
  }, [])

  // Each successful load of the user data refreshes the form and the owned robots/tasks.
  const ownRowRef = useRef(ownRow)
  ownRowRef.current = ownRow
  useEffect(() => {
    if (!loadVersion) return
    setSelfForm(profileFormFrom(ownRowRef.current))
    loadAssets()
  }, [loadVersion, loadAssets])

  async function saveProfile(event: FormEvent) {
    event.preventDefault()
    setSelfSubmitting(true)
    try {
      const payload = await postJson<{ user?: SessionUser }>('/api/web/users/me/update', profilePayload(selfForm))
      if (payload?.user) {
        setSessionUser(payload.user)
      }
      pushFlash('个人信息已更新', 'success')
      await onChanged()
    } catch (error) {
      pushFlash(errorMessage(error, '更新个人信息失败'), 'error')
    } finally {
      setSelfSubmitting(false)
    }
  }

  async function deleteRobot(robot: OwnedRobot) {
    if (!robot?.id) return
    if (!window.confirm(`确认删除机器人 ${robot.name || robot.device_id || `#${robot.id}`} 吗？`)) return

    setRobotOpsLoadingId(robot.id)
    try {
      await postJson(`/api/robot/delete/${robot.id}`, {})
      pushFlash('机器人已删除', 'success')
      await onChanged()
    } catch (error) {
      pushFlash(errorMessage(error, '删除机器人失败'), 'error')
    } finally {
      setRobotOpsLoadingId(null)
    }
  }

  async function setPatrolTaskStatus(task: OwnedPatrolTask, status: string) {
    if (!task?.id) return
    setPatrolOpsLoadingId(task.id)
    try {
      await postJson(`/api/robot/task/update/${task.id}`, { status })
      pushFlash(`任务状态已更新为${patrolStatusText(status)}`, 'success')
      await loadAssets()
    } catch (error) {
      pushFlash(errorMessage(error, '更新任务状态失败'), 'error')
    } finally {
      setPatrolOpsLoadingId(null)
    }
  }

  async function deletePatrolTask(task: OwnedPatrolTask) {
    if (!task?.id) return
    if (!window.confirm(`确认删除巡检任务 ${task.name || `#${task.id}`} 吗？`)) return

    setPatrolOpsLoadingId(task.id)
    try {
      await postJson(`/api/robot/task/delete/${task.id}`, {})
      pushFlash('巡检任务已删除', 'success')
      await loadAssets()
    } catch (error) {
      pushFlash(errorMessage(error, '删除巡检任务失败'), 'error')
    } finally {
      setPatrolOpsLoadingId(null)
    }
  }

  return (
    <section className="user-self-layout" aria-label="个人中心主体">
      <div className="card-surface self-profile-card">
        <div className="profile-card-head">
          <span className="profile-avatar">{currentUsername.slice(0, 1).toUpperCase()}</span>
          <div className="profile-head-texts">
            <h3 className="section-title section-title-sm">个人信息卡</h3>
            <div className="profile-username">{currentUsername}</div>
            <div className="profile-meta">
              <span className="profile-tag">{currentRoleText}</span>
              <span className="profile-tag">{ownRow?.organization || '未填写单位'}</span>
            </div>
          </div>
        </div>

        <p className="user-page-subtitle" style={{ marginTop: 0 }}>
          仅管理当前登录账号信息，保存后即时生效。
        </p>

        <form className="self-profile-form" onSubmit={saveProfile}>
          <label className="field-block">
            <span>用户名</span>
            <input value={selfForm.username} onChange={updateSelf('username')} maxLength={50} minLength={3} required />
          </label>
          <label className="field-block">
            <span>所属单位</span>
            <input value={selfForm.organization} onChange={updateSelf('organization')} maxLength={120} required placeholder="例如：XX 环卫中心" />
          </label>
          <label className="field-block">
            <span>新密码（留空不修改）</span>
            <input value={selfForm.password} onChange={updateSelf('password')} type="password" minLength={6} placeholder="至少 6 位" />
          </label>
          <label className="field-block">
            <span>确认新密码</span>
            <input value={selfForm.confirm_password} onChange={updateSelf('confirm_password')} type="password" minLength={6} placeholder="再次输入新密码" />
          </label>
          <div className="create-actions">
            <button type="submit" disabled={selfSubmitting}>
              {selfSubmitting ? '保存中...' : '保存我的信息'}
            </button>
          </div>
        </form>
      </div>

      <div className="card-surface self-assets-card">
        <div className="assets-head">
          <h3 className="section-title section-title-sm">我的机器人与任务</h3>
          <button type="button" className="self-square-btn" disabled={assetsLoading} onClick={loadAssets}>
            {assetsLoading ? '刷新中...' : '刷新'}
          </button>
        </div>

        {ownRow && (
          <div className="self-overview-grid">
            <div className="overview-item">
              <span className="overview-label">用户 ID</span>
              <span className="overview-value">#{ownRow.id}</span>
            </div>
            <div className="overview-item">
              <span className="overview-label">用户名</span>
              <span className="overview-value">{ownRow.username || '-'}</span>
            </div>
          </div>
        )}

        <div className="asset-section">
          <div className="asset-section-head">
            <h4>我的机器人</h4>
            <Link to="/robot" className="self-square-btn">打开机器人管理</Link>
          </div>
          {assetsLoading ? (
            <div className="page-loading">载入中...</div>
          ) : !myRobots.length ? (
            <div className="empty-state">你还没有绑定机器人</div>
          ) : (
            <ul className="asset-list">
              {myRobots.map((robot) => (
                <li key={`robot-${robot.id}`} className="asset-item">
                  <div className="asset-main">
                    <div className="asset-title">{robot.name || '未命名机器人'}</div>
                    <div className="asset-meta">设备ID：{robot.device_id || '-'} · 状态：{robot.status || '-'}</div>
                  </div>
                  <div className="asset-actions">
                    <Link className="self-square-btn" to={`/robot/${robot.id}`}>进入控制</Link>
                    <button
                      type="button"
                      className="self-square-btn self-square-btn-danger"
                      disabled={robotOpsLoadingId === robot.id}
                      onClick={() => deleteRobot(robot)}
                    >
                      {robotOpsLoadingId === robot.id ? '删除中...' : '删除'}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="asset-section">
          <div className="asset-section-head">
            <h4>我的巡检任务</h4>
            <Link to="/result" className="self-square-btn">查看检测任务</Link>
          </div>
          {assetsLoading ? (
            <div className="page-loading">载入中...</div>
          ) : !myPatrolTasks.length ? (
            <div className="empty-state">暂无巡检任务</div>
          ) : (
            <ul className="asset-list">
              {myPatrolTasks.map((task) => {
                const statusCode = String(task.status || '').toUpperCase()
                const busy = patrolOpsLoadingId === task.id
                return (
                  <li key={`task-${task.id}`} className="asset-item">
                    <div className="asset-main">
                      <div className="asset-title">{task.name || `任务 #${task.id}`}</div>
                      <div className="asset-meta">
                        状态：{patrolStatusText(task.status)} · 机器人ID：#{task.robot_id} · 创建：{formatDateTime(task.created_at)}
                      </div>
                    </div>
                    <div className="asset-actions">
                      <button
                        type="button"
                        className="self-square-btn"
                        disabled={busy || statusCode === 'RUNNING'}
                        onClick={() => setPatrolTaskStatus(task, 'RUNNING')}
                      >
                        运行
                      </button>
                      <button
                        type="button"
                        className="self-square-btn"
                        disabled={busy || statusCode === 'PAUSED'}
                        onClick={() => setPatrolTaskStatus(task, 'PAUSED')}
                      >
                        暂停
                      </button>
                      <button
                        type="button"
                        className="self-square-btn self-square-btn-danger"
                        disabled={busy}
                        onClick={() => deletePatrolTask(task)}
                      >
                        {busy ? '处理中...' : '删除'}
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </section>
  )
}
