import { useState, type FormEvent, type MouseEvent } from 'react'
import CssTransition from '../../components/CssTransition'
import { useNewKeys } from '../../hooks/useNewKeys'
import { errorMessage, postJson } from '../../lib/api'
import { fieldUpdater } from '../../lib/forms'
import { pushFlash } from '../../stores/session'
import { EMPTY_PROFILE_FORM, profileFormFrom, profilePayload, roleText, type ProfileForm, type UserRow } from './shared'

const EMPTY_CREATE_FORM = { username: '', organization: '', password: '', confirm_password: '', security_code: '', role: 'user' }

interface Props {
  rows: UserRow[]
  loading: boolean
  /** Reload the user list after a change. */
  onChanged: () => Promise<void>
}

/** Admin view: create users, list all users, change roles, edit or delete accounts. */
export default function AdminUsersSection({ rows, loading, onChanged }: Props) {
  const [submitting, setSubmitting] = useState(false)
  const [updatingUserId, setUpdatingUserId] = useState<number | null>(null)
  const [deletingUserId, setDeletingUserId] = useState<number | null>(null)
  const [editingUserId, setEditingUserId] = useState<number | null>(null)
  const [editingRowName, setEditingRowName] = useState('')
  const [savingProfileUserId, setSavingProfileUserId] = useState<number | null>(null)

  const [createForm, setCreateForm] = useState(EMPTY_CREATE_FORM)
  const [editForm, setEditForm] = useState<ProfileForm>(EMPTY_PROFILE_FORM)
  const updateCreate = fieldUpdater(setCreateForm)
  const updateEdit = fieldUpdater(setEditForm)

  const newRowIds = useNewKeys(rows, (row) => row.id)

  async function createUser(event: FormEvent) {
    event.preventDefault()
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
      await onChanged()
    } catch (error) {
      pushFlash(errorMessage(error, '创建用户失败'), 'error')
    } finally {
      setSubmitting(false)
    }
  }

  async function toggleRole(row: UserRow) {
    const nextRole = row.role === 'admin' ? 'user' : 'admin'
    setUpdatingUserId(row.id)
    try {
      await postJson(`/api/web/admin/users/${row.id}/role`, { role: nextRole })
      pushFlash('用户角色已更新', 'success')
      await onChanged()
    } catch (error) {
      pushFlash(errorMessage(error, '更新用户角色失败'), 'error')
    } finally {
      setUpdatingUserId(null)
    }
  }

  function startEdit(row: UserRow) {
    if (row.is_current_user) {
      pushFlash('请在个人中心修改当前登录用户信息', 'warning')
      return
    }
    setEditingUserId(row.id)
    setEditingRowName(row.username || '')
    setEditForm(profileFormFrom(row))
  }

  function cancelEdit() {
    setEditingUserId(null)
    setEditingRowName('')
    setEditForm(EMPTY_PROFILE_FORM)
  }

  async function saveUserProfile(event: FormEvent) {
    event.preventDefault()
    const targetUserId = editingUserId
    if (!targetUserId) {
      return
    }

    setSavingProfileUserId(targetUserId)
    try {
      await postJson(`/api/web/admin/users/${targetUserId}/update`, profilePayload(editForm))
      pushFlash('用户信息已更新', 'success')
      cancelEdit()
      await onChanged()
    } catch (error) {
      pushFlash(errorMessage(error, '更新用户信息失败'), 'error')
    } finally {
      setSavingProfileUserId(null)
    }
  }

  async function removeUser(row: UserRow) {
    if (!window.confirm(`确认删除用户 ${row.username} 吗？`)) {
      return
    }
    setDeletingUserId(row.id)
    try {
      await postJson(`/api/web/admin/users/${row.id}/delete`, {})
      pushFlash('用户删除成功', 'success')
      await onChanged()
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
    <>
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
    </>
  )
}
