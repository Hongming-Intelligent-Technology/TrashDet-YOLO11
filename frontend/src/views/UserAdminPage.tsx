import { useCallback, useEffect, useState } from 'react'
import { ApiError, errorMessage, getJson } from '../lib/api'
import { pushFlash, useSession } from '../stores/session'
import AdminUsersSection from './userAdmin/AdminUsersSection'
import SelfProfileSection from './userAdmin/SelfProfileSection'
import type { UserRow } from './userAdmin/shared'
import './UserAdminPage.css'

interface UserSummary {
  total: number
  admin_count: number
  user_count: number
}

interface AdminUsersResponse {
  can_manage?: boolean
  users?: UserRow[]
  summary?: UserSummary
}

const EMPTY_SUMMARY: UserSummary = { total: 0, admin_count: 0, user_count: 0 }

export default function UserAdminPage() {
  const { user: authUser } = useSession()

  const [loading, setLoading] = useState(false)
  const [rows, setRows] = useState<UserRow[]>([])
  const [loadError, setLoadError] = useState('')
  const [canManage, setCanManage] = useState(false)
  const [summary, setSummary] = useState<UserSummary>(EMPTY_SUMMARY)
  const [loadVersion, setLoadVersion] = useState(0)

  const currentUserRow = rows.find((row) => row.is_current_user) || rows[0] || null
  const currentUsername = String(currentUserRow?.username || authUser?.username || '').trim() || '-'
  const currentRoleText = authUser?.role === 'admin' ? '管理员' : '普通用户'
  const pageTitle = canManage ? '账号与权限管理' : '个人信息管理'
  const pageSubtitle = canManage
    ? '管理员模式：可查看并管理所有用户（接口：/api/web/admin/users）'
    : '普通用户模式：仅管理当前登录账号信息'

  // Admins get every user; regular users get only their own row.
  const loadUsers = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const payload = await getJson<AdminUsersResponse>('/api/web/admin/users')
      setCanManage(Boolean(payload.can_manage))
      setRows([...(payload.users || [])].sort((a, b) => Number(a.id || 0) - Number(b.id || 0)))
      setSummary(payload.summary || EMPTY_SUMMARY)
      setLoadVersion((version) => version + 1)
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
  }, [])

  useEffect(() => {
    loadUsers()
  }, [loadUsers])

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
          <AdminUsersSection rows={rows} loading={loading} onChanged={loadUsers} />
        ) : (
          <SelfProfileSection
            ownRow={currentUserRow}
            currentUsername={currentUsername}
            currentRoleText={currentRoleText}
            loadVersion={loadVersion}
            onChanged={loadUsers}
          />
        )}
      </div>
    </div>
  )
}
