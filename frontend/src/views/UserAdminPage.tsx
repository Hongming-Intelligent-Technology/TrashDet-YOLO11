import { useCallback, useEffect, useState, type FormEvent, type MouseEvent } from 'react'
import { Link } from 'react-router'
import CssTransition from '../components/CssTransition'
import { useNewKeys } from '../hooks/useNewKeys'
import { ApiError, errorMessage, getJson, postJson } from '../lib/api'
import { fieldUpdater } from '../lib/forms'
import { pushFlash, setSessionUser, useSession, type SessionUser } from '../stores/session'
import './UserAdminPage.css'

interface UserRow {
  id: number
  username?: string
  organization?: string | null
  role?: string
  is_current_user?: boolean
}

interface UserSummary {
  total: number
  admin_count: number
  user_count: number
}

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

interface AdminUsersResponse {
  can_manage?: boolean
  users?: UserRow[]
  summary?: UserSummary
}

const EMPTY_SUMMARY: UserSummary = { total: 0, admin_count: 0, user_count: 0 }
const EMPTY_CREATE_FORM = { username: '', organization: '', password: '', confirm_password: '', security_code: '', role: 'user' }
const EMPTY_PROFILE_FORM = { username: '', organization: '', password: '', confirm_password: '' }
type ProfileForm = typeof EMPTY_PROFILE_FORM

function byIdDesc<T extends { id?: number }>(a: T, b: T) {
  return Number(b.id || 0) - Number(a.id || 0)
}

function roleText(role?: string) {
  return role === 'admin' ? '管理员' : '普通用户'
}

function patrolStatusText(status?: string | null) {
  const code = String(status || '').toUpperCase()
  if (code === 'PLANNED') return '待执行'
  if (code === 'RUNNING') return '执行中'
  if (code === 'PAUSED') return '已暂停'
  if (code === 'DONE') return '已完成'
  if (code === 'CANCELLED') return '已取消'
  return status || '-'
}

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return String(value)
  return dt.toLocaleString('zh-CN', { hour12: false })
}

/** Profile fields as sent to the backend: names trimmed, passwords as typed. */
function profilePayload(form: ProfileForm) {
  return {
    username: form.username.trim(),
    organization: form.organization.trim(),
    password: form.password,
    confirm_password: form.confirm_password,
  }
}

export default function UserAdminPage() {
  const { user: authUser } = useSession()

  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [updatingUserId, setUpdatingUserId] = useState<number | null>(null)
  const [deletingUserId, setDeletingUserId] = useState<number | null>(null)
  const [editingUserId, setEditingUserId] = useState<number | null>(null)
  const [savingProfileUserId, setSavingProfileUserId] = useState<number | null>(null)
  const [selfAssetsLoading, setSelfAssetsLoading] = useState(false)
  const [robotOpsLoadingId, setRobotOpsLoadingId] = useState<number | null>(null)
  const [patrolOpsLoadingId, setPatrolOpsLoadingId] = useState<number | null>(null)
  const [editingRowName, setEditingRowName] = useState('')
  const [rows, setRows] = useState<UserRow[]>([])
  const [myRobots, setMyRobots] = useState<OwnedRobot[]>([])
  const [myPatrolTasks, setMyPatrolTasks] = useState<OwnedPatrolTask[]>([])
  const [loadError, setLoadError] = useState('')
  const [canManage, setCanManage] = useState(false)
  const [selfSubmitting, setSelfSubmitting] = useState(false)
  const [summary, setSummary] = useState<UserSummary>(EMPTY_SUMMARY)

  const [createForm, setCreateForm] = useState(EMPTY_CREATE_FORM)
  const [editForm, setEditForm] = useState<ProfileForm>(EMPTY_PROFILE_FORM)
  const [selfForm, setSelfForm] = useState<ProfileForm>(EMPTY_PROFILE_FORM)
  const updateCreate = fieldUpdater(setCreateForm)
  const updateEdit = fieldUpdater(setEditForm)
  const updateSelf = fieldUpdater(setSelfForm)

  const newRowIds = useNewKeys(rows, (row) => row.id)

  const currentUserRow = rows.find((row) => row.is_current_user) || rows[0] || null
  const currentUsername = String(currentUserRow?.username || selfForm.username || authUser?.username || '').trim() || '-'
  const currentRoleText = authUser?.role === 'admin' ? '管理员' : '普通用户'
  const pageTitle = canManage ? '账号与权限管理' : '个人信息管理'
  const pageSubtitle = canManage
    ? '管理员模式：可查看并管理所有用户（接口：/api/web/admin/users）'
    : '普通用户模式：仅管理当前登录账号信息'

  const loadSelfAssets = useCallback(async () => {
    setSelfAssetsLoading(true)
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
      setSelfAssetsLoading(false)
    }
  }, [])

  const loadUsers = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const payload = await getJson<AdminUsersResponse>('/api/web/admin/users')
      const manage = Boolean(payload.can_manage)
      const sortedRows = [...(payload.users || [])].sort((a, b) => Number(a.id || 0) - Number(b.id || 0))
      setCanManage(manage)
      setRows(sortedRows)
      setSummary(payload.summary || EMPTY_SUMMARY)
      setEditingUserId(null)
      if (!manage) {
        const ownRow = sortedRows[0]
        setSelfForm(ownRow
          ? { username: ownRow.username || '', organization: ownRow.organization || '', password: '', confirm_password: '' }
          : EMPTY_PROFILE_FORM)
        await loadSelfAssets()
      } else {
        setMyRobots([])
        setMyPatrolTasks([])
      }
    } catch (error) {
      setRows([])
      setCanManage(false)
      setSummary(EMPTY_SUMMARY)
      if (error instanceof ApiError && error.status === 401) {
        setLoadError('当前登录已失效，请重新登录后再加载用户数据。')
      } else {
        setLoadError(errorMessage(error, '用户列表加载失败，请检查后端服务和数据库连接。'))
      }
      pushFlash(errorMessage(error, '用户列表加载失败'), 'error')
    } finally {
      setLoading(false)
    }
  }, [loadSelfAssets])

  useEffect(() => {
    loadUsers()
  }, [loadUsers])

  async function deleteMyRobot(robot: OwnedRobot) {
    if (!robot?.id) return
    if (!window.confirm(`确认删除机器人 ${robot.name || robot.device_id || `#${robot.id}`} 吗？`)) return

    setRobotOpsLoadingId(robot.id)
    try {
      await postJson(`/api/robot/delete/${robot.id}`, {})
      pushFlash('机器人已删除', 'success')
      await loadUsers()
    } catch (error) {
      pushFlash(errorMessage(error, '删除机器人失败'), 'error')
    } finally {
      setRobotOpsLoadingId(null)
    }
  }

  async function setMyPatrolTaskStatus(task: OwnedPatrolTask, status: string) {
    if (!task?.id) return
    setPatrolOpsLoadingId(task.id)
    try {
      await postJson(`/api/robot/task/update/${task.id}`, { status })
      pushFlash(`任务状态已更新为${patrolStatusText(status)}`, 'success')
      await loadSelfAssets()
    } catch (error) {
      pushFlash(errorMessage(error, '更新任务状态失败'), 'error')
    } finally {
      setPatrolOpsLoadingId(null)
    }
  }

  async function deleteMyPatrolTask(task: OwnedPatrolTask) {
    if (!task?.id) return
    if (!window.confirm(`确认删除巡检任务 ${task.name || `#${task.id}`} 吗？`)) return

    setPatrolOpsLoadingId(task.id)
    try {
      await postJson(`/api/robot/task/delete/${task.id}`, {})
      pushFlash('巡检任务已删除', 'success')
      await loadSelfAssets()
    } catch (error) {
      pushFlash(errorMessage(error, '删除巡检任务失败'), 'error')
    } finally {
      setPatrolOpsLoadingId(null)
    }
  }

  async function saveCurrentUserProfile(event: FormEvent) {
    event.preventDefault()
    if (canManage) {
      pushFlash('管理员请在用户列表中编辑账号信息', 'warning')
      return
    }

    setSelfSubmitting(true)
    try {
      const payload = await postJson<{ user?: SessionUser }>('/api/web/users/me/update', profilePayload(selfForm))
      if (payload?.user) {
        setSessionUser(payload.user)
      }
      pushFlash('个人信息已更新', 'success')
      await loadUsers()
    } catch (error) {
      pushFlash(errorMessage(error, '更新个人信息失败'), 'error')
    } finally {
      setSelfSubmitting(false)
    }
  }

  async function createUser(event: FormEvent) {
    event.preventDefault()
    if (!canManage) {
      pushFlash('当前账号只有查看权限，无法创建用户', 'warning')
      return
    }
    setSubmitting(true)
    try {
      await postJson('/api/web/admin/users', {
        username: createForm.username.trim(),
        organization: createForm.organization.trim(),
        password: createForm.password,
        confirm_password: createForm.confirm_password,
        security_code: createForm.security_code.trim(),
        role: createForm.role,
      })
      pushFlash('用户创建成功', 'success')
      setCreateForm(EMPTY_CREATE_FORM)
      await loadUsers()
    } catch (error) {
      pushFlash(errorMessage(error, '创建用户失败'), 'error')
    } finally {
      setSubmitting(false)
    }
  }

  async function toggleRole(row: UserRow) {
    if (!canManage) {
      pushFlash('当前账号只有查看权限，无法修改角色', 'warning')
      return
    }
    const nextRole = row.role === 'admin' ? 'user' : 'admin'
    setUpdatingUserId(row.id)
    try {
      await postJson(`/api/web/admin/users/${row.id}/role`, { role: nextRole })
      pushFlash('用户角色已更新', 'success')
      await loadUsers()
    } catch (error) {
      pushFlash(errorMessage(error, '更新用户角色失败'), 'error')
    } finally {
      setUpdatingUserId(null)
    }
  }

  function startEdit(row: UserRow) {
    if (!canManage) {
      pushFlash('当前账号只有查看权限，无法编辑用户信息', 'warning')
      return
    }
    if (row.is_current_user) {
      pushFlash('请在个人中心修改当前登录用户信息', 'warning')
      return
    }
    setEditingUserId(row.id)
    setEditingRowName(row.username || '')
    setEditForm({ username: row.username || '', organization: row.organization || '', password: '', confirm_password: '' })
  }

  function cancelEdit() {
    setEditingUserId(null)
    setEditingRowName('')
    setEditForm(EMPTY_PROFILE_FORM)
  }

  async function saveUserProfile(event: FormEvent) {
    event.preventDefault()
    if (!canManage) {
      pushFlash('当前账号只有查看权限，无法编辑用户信息', 'warning')
      return
    }
    const targetUserId = editingUserId
    if (!targetUserId) {
      return
    }

    setSavingProfileUserId(targetUserId)
    try {
      await postJson(`/api/web/admin/users/${targetUserId}/update`, profilePayload(editForm))
      pushFlash('用户信息已更新', 'success')
      cancelEdit()
      await loadUsers()
    } catch (error) {
      pushFlash(errorMessage(error, '更新用户信息失败'), 'error')
    } finally {
      setSavingProfileUserId(null)
    }
  }

  async function removeUser(row: UserRow) {
    if (!canManage) {
      pushFlash('当前账号只有查看权限，无法删除用户', 'warning')
      return
    }
    if (!window.confirm(`确认删除用户 ${row.username} 吗？`)) {
      return
    }
    setDeletingUserId(row.id)
    try {
      await postJson(`/api/web/admin/users/${row.id}/delete`, {})
      pushFlash('用户删除成功', 'success')
      await loadUsers()
    } catch (error) {
      pushFlash(errorMessage(error, '删除用户失败'), 'error')
    } finally {
      setDeletingUserId(null)
    }
  }

  function onMaskClick(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) {
      cancelEdit()
    }
  }

  return (
    <div className="scope-user-admin panel page-panel user-admin-page">
      <div className="panel-title">用户管理 · User Admin</div>
      <div className="panel-body user-admin-body">
        <section className="user-page-head" aria-label="页面头部">
          <div>
            <h3 className="section-title">{pageTitle}</h3>
            <p className="user-page-subtitle">{pageSubtitle}</p>
          </div>
          <div className="head-right">
            <span className="login-badge">当前用户：{currentUsername}</span>
            <span className="login-badge">当前身份：{currentRoleText}</span>
            <button type="button" className="btn-detail" onClick={loadUsers}>刷新数据</button>
          </div>
        </section>

        {loadError && (
          <div className="error-banner">
            <strong>加载失败：</strong>{loadError}
          </div>
        )}

        {canManage && (
          <section className="user-summary" aria-label="用户摘要">
            <div className="summary-item">
              <div className="summary-label">用户总数</div>
              <div className="summary-value">{summary.total}</div>
            </div>
            <div className="summary-item">
              <div className="summary-label">管理员</div>
              <div className="summary-value">{summary.admin_count}</div>
            </div>
            <div className="summary-item">
              <div className="summary-label">普通用户</div>
              <div className="summary-value">{summary.user_count}</div>
            </div>
          </section>
        )}

        {canManage ? (
          <section className="user-main-grid" aria-label="用户管理主体">
            <div className="user-create card-surface" aria-label="创建用户">
              <h3 className="section-title section-title-sm">创建新用户</h3>
              <form className="create-grid" onSubmit={createUser}>
                <label className="field-block">
                  <span>用户名</span>
                  <input value={createForm.username} onChange={updateCreate('username')} maxLength={50} minLength={3} required />
                </label>
                <label className="field-block">
                  <span>所属单位</span>
                  <input value={createForm.organization} onChange={updateCreate('organization')} maxLength={120} required placeholder="例如：XX 环卫中心" />
                </label>
                <label className="field-block">
                  <span>密码</span>
                  <input value={createForm.password} onChange={updateCreate('password')} type="password" minLength={6} required />
                </label>
                <label className="field-block">
                  <span>确认密码</span>
                  <input value={createForm.confirm_password} onChange={updateCreate('confirm_password')} type="password" minLength={6} required />
                </label>
                <label className="field-block">
                  <span>安全码</span>
                  <input value={createForm.security_code} onChange={updateCreate('security_code')} maxLength={32} required />
                </label>
                <label className="field-block">
                  <span>角色</span>
                  <select value={createForm.role} onChange={updateCreate('role')} required>
                    <option value="user">普通用户</option>
                    <option value="admin">管理员</option>
                  </select>
                </label>
                <div className="create-actions">
                  <button type="submit" disabled={submitting}>
                    {submitting ? '创建中...' : '创建用户'}
                  </button>
                </div>
              </form>
            </div>

            <div className="user-list card-surface" aria-label="用户列表">
              <h3 className="section-title section-title-sm">用户列表</h3>
              {loading ? (
                <div className="page-loading">载入中...</div>
              ) : !rows.length ? (
                <div className="empty-state">暂无用户数据（后端 user 表）</div>
              ) : (
                <div className="user-list-shell">
                  <div className="user-list-head">
                    <span>用户</span>
                    <span>所属单位</span>
                    <span>角色</span>
                    <span className="col-right">操作</span>
                  </div>
                  <ul className="user-list-rows">
                    {rows.map((row) => (
                      <li key={row.id} className={`user-list-row${newRowIds.has(row.id) ? ' user-row-pop-enter-active' : ''}`}>
                        <div className="user-col user-col-user">
                          <div className="user-mainline">
                            <span className="user-avatar">{row.username ? row.username.slice(0, 1).toUpperCase() : '?'}</span>
                            <div className="user-texts">
                              <div className="user-item-name">
                                {row.username}
                                {row.is_current_user && <span className="current-tag">当前登录</span>}
                              </div>
                              <span className="user-item-id">ID #{row.id}</span>
                            </div>
                          </div>
                        </div>

                        <div className="user-col user-col-role">
                          <span className="organization-tag">{row.organization || '-'}</span>
                        </div>

                        <div className="user-col user-col-role">
                          <span className={row.role === 'admin' ? 'role-admin' : 'role-user'}>{roleText(row.role)}</span>
                        </div>

                        <div className="user-col user-col-actions">
                          <button
                            type="button"
                            className="btn-detail"
                            disabled={Boolean(row.is_current_user) || editingUserId !== null}
                            onClick={() => startEdit(row)}
                          >
                            编辑信息
                          </button>
                          <button
                            type="button"
                            className="btn-detail"
                            disabled={updatingUserId === row.id || editingUserId !== null || (Boolean(row.is_current_user) && row.role === 'admin')}
                            onClick={() => toggleRole(row)}
                          >
                            {updatingUserId === row.id ? '更新中...' : row.role === 'admin' ? '降为普通用户' : '设为管理员'}
                          </button>
                          <button
                            type="button"
                            className="btn-delete"
                            disabled={deletingUserId === row.id || editingUserId !== null || Boolean(row.is_current_user)}
                            onClick={() => removeUser(row)}
                          >
                            {deletingUserId === row.id ? '删除中...' : '删除'}
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </section>
        ) : (
          <section className="user-self-layout" aria-label="个人中心主体">
            <div className="card-surface self-profile-card">
              <div className="profile-card-head">
                <span className="profile-avatar">{currentUsername.slice(0, 1).toUpperCase()}</span>
                <div className="profile-head-texts">
                  <h3 className="section-title section-title-sm">个人信息卡</h3>
                  <div className="profile-username">{currentUsername}</div>
                  <div className="profile-meta">
                    <span className="profile-tag">{currentRoleText}</span>
                    <span className="profile-tag">{currentUserRow?.organization || '未填写单位'}</span>
                  </div>
                </div>
              </div>

              <p className="user-page-subtitle" style={{ marginTop: 0 }}>
                仅管理当前登录账号信息，保存后即时生效。
              </p>

              <form className="self-profile-form" onSubmit={saveCurrentUserProfile}>
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
                <button type="button" className="self-square-btn" disabled={selfAssetsLoading} onClick={loadSelfAssets}>
                  {selfAssetsLoading ? '刷新中...' : '刷新'}
                </button>
              </div>

              {currentUserRow && (
                <div className="self-overview-grid">
                  <div className="overview-item">
                    <span className="overview-label">用户 ID</span>
                    <span className="overview-value">#{currentUserRow.id}</span>
                  </div>
                  <div className="overview-item">
                    <span className="overview-label">用户名</span>
                    <span className="overview-value">{currentUserRow.username || '-'}</span>
                  </div>
                </div>
              )}

              <div className="asset-section">
                <div className="asset-section-head">
                  <h4>我的机器人</h4>
                  <Link to="/robot" className="self-square-btn">打开机器人管理</Link>
                </div>
                {selfAssetsLoading ? (
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
                            onClick={() => deleteMyRobot(robot)}
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
                {selfAssetsLoading ? (
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
                              onClick={() => setMyPatrolTaskStatus(task, 'RUNNING')}
                            >
                              运行
                            </button>
                            <button
                              type="button"
                              className="self-square-btn"
                              disabled={busy || statusCode === 'PAUSED'}
                              onClick={() => setMyPatrolTaskStatus(task, 'PAUSED')}
                            >
                              暂停
                            </button>
                            <button
                              type="button"
                              className="self-square-btn self-square-btn-danger"
                              disabled={busy}
                              onClick={() => deleteMyPatrolTask(task)}
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
        )}

        <CssTransition name="edit-modal-fade" show={editingUserId !== null} durationMs={180}>
          <div className="edit-modal-mask" onClick={onMaskClick}>
            <section className="edit-modal-card card-surface" aria-label="编辑用户信息卡片">
              <h3 className="section-title section-title-sm">编辑成员信息</h3>
              <p className="user-page-subtitle" style={{ marginTop: 0 }}>
                用户 ID #{editingUserId} · 当前用户名：{editingRowName || '-'}
              </p>
              <form className="edit-form-grid" onSubmit={saveUserProfile}>
                <label className="field-block">
                  <span>用户名</span>
                  <input value={editForm.username} onChange={updateEdit('username')} maxLength={50} minLength={3} required />
                </label>
                <label className="field-block">
                  <span>所属单位</span>
                  <input value={editForm.organization} onChange={updateEdit('organization')} maxLength={120} required placeholder="例如：XX 环卫中心" />
                </label>
                <label className="field-block">
                  <span>新密码（留空则不修改）</span>
                  <input value={editForm.password} onChange={updateEdit('password')} type="password" minLength={6} placeholder="至少 6 位" />
                </label>
                <label className="field-block">
                  <span>确认新密码</span>
                  <input value={editForm.confirm_password} onChange={updateEdit('confirm_password')} type="password" minLength={6} placeholder="再次输入新密码" />
                </label>
                <p className="user-page-subtitle" style={{ marginTop: -2 }}>如不需要重置密码，请保持新密码和确认新密码为空。</p>
                <div className="edit-actions">
                  <button type="submit" disabled={savingProfileUserId !== null}>
                    {savingProfileUserId !== null ? '保存中...' : '保存修改'}
                  </button>
                  <button type="button" disabled={savingProfileUserId !== null} onClick={cancelEdit}>
                    取消
                  </button>
                </div>
              </form>
            </section>
          </div>
        </CssTransition>
      </div>
    </div>
  )
}
