<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { getJson, postJson } from '../lib/api'
import { pushFlash, sessionState, setSessionUser } from '../stores/session'

const loading = ref(false)
const submitting = ref(false)
const updatingUserId = ref(null)
const deletingUserId = ref(null)
const editingUserId = ref(null)
const savingProfileUserId = ref(null)
const selfAssetsLoading = ref(false)
const robotOpsLoadingId = ref(null)
const patrolOpsLoadingId = ref(null)
const editingRowName = ref('')
const rows = ref([])
const myRobots = ref([])
const myPatrolTasks = ref([])
const loadError = ref('')
const canManage = ref(false)
const selfSubmitting = ref(false)
const summary = ref({
  total: 0,
  admin_count: 0,
  user_count: 0,
})

const createForm = reactive({
  username: '',
  organization: '',
  password: '',
  confirm_password: '',
  security_code: '',
  role: 'user',
})

const editForm = reactive({
  username: '',
  organization: '',
  password: '',
  confirm_password: '',
})

const selfForm = reactive({
  username: '',
  organization: '',
  password: '',
  confirm_password: '',
})

const authUser = computed(() => sessionState.user)
const hasRows = computed(() => rows.value.length > 0)
const currentUserRow = computed(() => rows.value.find((row) => row.is_current_user) || rows.value[0] || null)
const currentUsername = computed(() => {
  const candidate = String(
    currentUserRow.value?.username || selfForm.username || authUser.value?.username || '',
  ).trim()
  return candidate || '-'
})
const currentRoleText = computed(() => (authUser.value?.role === 'admin' ? '管理员' : '普通用户'))
const pageTitle = computed(() => (canManage.value ? '账号与权限管理' : '个人信息管理'))
const pageSubtitle = computed(() => (
  canManage.value
    ? '管理员模式：可查看并管理所有用户（接口：/api/web/admin/users）'
    : '普通用户模式：仅管理当前登录账号信息'
))
const hasMyRobots = computed(() => myRobots.value.length > 0)
const hasMyPatrolTasks = computed(() => myPatrolTasks.value.length > 0)

function resetSummary() {
  summary.value = { total: 0, admin_count: 0, user_count: 0 }
}

function roleText(role) {
  return role === 'admin' ? '管理员' : '普通用户'
}

function patrolStatusText(status) {
  const code = String(status || '').toUpperCase()
  if (code === 'PLANNED') return '待执行'
  if (code === 'RUNNING') return '执行中'
  if (code === 'PAUSED') return '已暂停'
  if (code === 'DONE') return '已完成'
  if (code === 'CANCELLED') return '已取消'
  return status || '-'
}

function formatDateTime(value) {
  if (!value) return '-'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return String(value)
  return dt.toLocaleString('zh-CN', { hour12: false })
}

function resetCreateForm() {
  createForm.username = ''
  createForm.organization = ''
  createForm.password = ''
  createForm.confirm_password = ''
  createForm.security_code = ''
  createForm.role = 'user'
}

function resetSelfForm() {
  selfForm.username = ''
  selfForm.organization = ''
  selfForm.password = ''
  selfForm.confirm_password = ''
}

function syncSelfFormFromRow(row) {
  if (!row) {
    resetSelfForm()
    return
  }
  selfForm.username = row.username || ''
  selfForm.organization = row.organization || ''
  selfForm.password = ''
  selfForm.confirm_password = ''
}

async function loadSelfAssets() {
  selfAssetsLoading.value = true
  try {
    const [robotPayload, taskPayload] = await Promise.all([
      getJson('/api/robot/list'),
      getJson('/api/robot/task/list'),
    ])
    myRobots.value = [...(robotPayload.robots || [])].sort((a, b) => Number(b.id || 0) - Number(a.id || 0))
    myPatrolTasks.value = [...(taskPayload.tasks || [])].sort((a, b) => Number(b.id || 0) - Number(a.id || 0))
  } catch (error) {
    myRobots.value = []
    myPatrolTasks.value = []
    pushFlash(error.message || '加载个人资产失败', 'error')
  } finally {
    selfAssetsLoading.value = false
  }
}

async function loadUsers() {
  loading.value = true
  loadError.value = ''
  try {
    const payload = await getJson('/api/web/admin/users')
    canManage.value = Boolean(payload.can_manage)
    rows.value = [...(payload.users || [])].sort((a, b) => Number(a.id || 0) - Number(b.id || 0))
    summary.value = payload.summary || { total: 0, admin_count: 0, user_count: 0 }
    editingUserId.value = null
    if (!canManage.value) {
      syncSelfFormFromRow(rows.value[0] || null)
      await loadSelfAssets()
    } else {
      myRobots.value = []
      myPatrolTasks.value = []
    }
  } catch (error) {
    rows.value = []
    canManage.value = false
    resetSummary()
    if (error?.status === 401) {
      loadError.value = '当前登录已失效，请重新登录后再加载用户数据。'
    } else {
      loadError.value = error.message || '用户列表加载失败，请检查后端服务和数据库连接。'
    }
    pushFlash(error.message || '用户列表加载失败', 'error')
  } finally {
    loading.value = false
  }
}

async function deleteMyRobot(robot) {
  if (!robot?.id) return
  if (!window.confirm(`确认删除机器人 ${robot.name || robot.device_id || `#${robot.id}`} 吗？`)) return

  robotOpsLoadingId.value = robot.id
  try {
    await postJson(`/api/robot/delete/${robot.id}`, {})
    pushFlash('机器人已删除', 'success')
    await loadUsers()
  } catch (error) {
    pushFlash(error.message || '删除机器人失败', 'error')
  } finally {
    robotOpsLoadingId.value = null
  }
}

async function setMyPatrolTaskStatus(task, status) {
  if (!task?.id) return
  patrolOpsLoadingId.value = task.id
  try {
    await postJson(`/api/robot/task/update/${task.id}`, { status })
    pushFlash(`任务状态已更新为${patrolStatusText(status)}`, 'success')
    await loadSelfAssets()
  } catch (error) {
    pushFlash(error.message || '更新任务状态失败', 'error')
  } finally {
    patrolOpsLoadingId.value = null
  }
}

async function deleteMyPatrolTask(task) {
  if (!task?.id) return
  if (!window.confirm(`确认删除巡检任务 ${task.name || `#${task.id}`} 吗？`)) return

  patrolOpsLoadingId.value = task.id
  try {
    await postJson(`/api/robot/task/delete/${task.id}`, {})
    pushFlash('巡检任务已删除', 'success')
    await loadSelfAssets()
  } catch (error) {
    pushFlash(error.message || '删除巡检任务失败', 'error')
  } finally {
    patrolOpsLoadingId.value = null
  }
}

async function saveCurrentUserProfile() {
  if (canManage.value) {
    pushFlash('管理员请在用户列表中编辑账号信息', 'warning')
    return
  }

  selfSubmitting.value = true
  try {
    const payload = await postJson('/api/web/users/me/update', {
      username: selfForm.username,
      organization: selfForm.organization,
      password: selfForm.password,
      confirm_password: selfForm.confirm_password,
    })
    if (payload?.user) {
      setSessionUser(payload.user)
    }
    pushFlash('个人信息已更新', 'success')
    await loadUsers()
  } catch (error) {
    pushFlash(error.message || '更新个人信息失败', 'error')
  } finally {
    selfSubmitting.value = false
  }
}

async function createUser() {
  if (!canManage.value) {
    pushFlash('当前账号只有查看权限，无法创建用户', 'warning')
    return
  }
  submitting.value = true
  try {
    await postJson('/api/web/admin/users', {
      username: createForm.username,
      organization: createForm.organization,
      password: createForm.password,
      confirm_password: createForm.confirm_password,
      security_code: createForm.security_code,
      role: createForm.role,
    })
    pushFlash('用户创建成功', 'success')
    resetCreateForm()
    await loadUsers()
  } catch (error) {
    pushFlash(error.message || '创建用户失败', 'error')
  } finally {
    submitting.value = false
  }
}

async function toggleRole(row) {
  if (!canManage.value) {
    pushFlash('当前账号只有查看权限，无法修改角色', 'warning')
    return
  }
  const nextRole = row.role === 'admin' ? 'user' : 'admin'
  updatingUserId.value = row.id
  try {
    await postJson(`/api/web/admin/users/${row.id}/role`, { role: nextRole })
    pushFlash('用户角色已更新', 'success')
    await loadUsers()
  } catch (error) {
    pushFlash(error.message || '更新用户角色失败', 'error')
  } finally {
    updatingUserId.value = null
  }
}

function startEdit(row) {
  if (!canManage.value) {
    pushFlash('当前账号只有查看权限，无法编辑用户信息', 'warning')
    return
  }
  if (row.is_current_user) {
    pushFlash('请在个人中心修改当前登录用户信息', 'warning')
    return
  }

  editingUserId.value = row.id
  editingRowName.value = row.username || ''
  editForm.username = row.username || ''
  editForm.organization = row.organization || ''
  editForm.password = ''
  editForm.confirm_password = ''
}

function cancelEdit() {
  editingUserId.value = null
  editingRowName.value = ''
  editForm.username = ''
  editForm.organization = ''
  editForm.password = ''
  editForm.confirm_password = ''
}

async function saveUserProfile() {
  if (!canManage.value) {
    pushFlash('当前账号只有查看权限，无法编辑用户信息', 'warning')
    return
  }

  const targetUserId = editingUserId.value
  if (!targetUserId) {
    return
  }

  savingProfileUserId.value = targetUserId
  try {
    await postJson(`/api/web/admin/users/${targetUserId}/update`, {
      username: editForm.username,
      organization: editForm.organization,
      password: editForm.password,
      confirm_password: editForm.confirm_password,
    })
    pushFlash('用户信息已更新', 'success')
    cancelEdit()
    await loadUsers()
  } catch (error) {
    pushFlash(error.message || '更新用户信息失败', 'error')
  } finally {
    savingProfileUserId.value = null
  }
}

async function removeUser(row) {
  if (!canManage.value) {
    pushFlash('当前账号只有查看权限，无法删除用户', 'warning')
    return
  }
  if (!window.confirm(`确认删除用户 ${row.username} 吗？`)) {
    return
  }

  deletingUserId.value = row.id
  try {
    await postJson(`/api/web/admin/users/${row.id}/delete`, {})
    pushFlash('用户删除成功', 'success')
    await loadUsers()
  } catch (error) {
    pushFlash(error.message || '删除用户失败', 'error')
  } finally {
    deletingUserId.value = null
  }
}

onMounted(loadUsers)
</script>

<template>
  <div class="panel page-panel user-admin-page">
    <div class="panel-title">用户管理 · User Admin</div>
    <div class="panel-body user-admin-body">
      <section class="user-page-head" aria-label="页面头部">
        <div>
          <h3 class="section-title">{{ pageTitle }}</h3>
          <p class="user-page-subtitle">{{ pageSubtitle }}</p>
        </div>
        <div class="head-right">
          <span class="login-badge">当前用户：{{ currentUsername }}</span>
          <span class="login-badge">当前身份：{{ currentRoleText }}</span>
          <button type="button" class="btn-detail" @click="loadUsers">刷新数据</button>
        </div>
      </section>

      <div v-if="loadError" class="error-banner">
        <strong>加载失败：</strong>{{ loadError }}
      </div>

      <section v-if="canManage" class="user-summary" aria-label="用户摘要">
        <div class="summary-item">
          <div class="summary-label">用户总数</div>
          <div class="summary-value">{{ summary.total }}</div>
        </div>
        <div class="summary-item">
          <div class="summary-label">管理员</div>
          <div class="summary-value">{{ summary.admin_count }}</div>
        </div>
        <div class="summary-item">
          <div class="summary-label">普通用户</div>
          <div class="summary-value">{{ summary.user_count }}</div>
        </div>
      </section>

      <section v-if="canManage" class="user-main-grid" aria-label="用户管理主体">
        <div class="user-create card-surface" aria-label="创建用户">
          <h3 class="section-title section-title-sm">创建新用户</h3>
          <form class="create-grid" @submit.prevent="createUser">
            <label class="field-block">
              <span>用户名</span>
              <input v-model.trim="createForm.username" maxlength="50" minlength="3" required>
            </label>
            <label class="field-block">
              <span>所属单位</span>
              <input v-model.trim="createForm.organization" maxlength="120" required placeholder="例如：XX 环卫中心">
            </label>
            <label class="field-block">
              <span>密码</span>
              <input v-model="createForm.password" type="password" minlength="6" required>
            </label>
            <label class="field-block">
              <span>确认密码</span>
              <input v-model="createForm.confirm_password" type="password" minlength="6" required>
            </label>
            <label class="field-block">
              <span>安全码</span>
              <input v-model.trim="createForm.security_code" maxlength="32" required>
            </label>
            <label class="field-block">
              <span>角色</span>
              <select v-model="createForm.role" required>
                <option value="user">普通用户</option>
                <option value="admin">管理员</option>
              </select>
            </label>
            <div class="create-actions">
              <button type="submit" :disabled="submitting">
                {{ submitting ? '创建中...' : '创建用户' }}
              </button>
            </div>
          </form>
        </div>

        <div class="user-list card-surface" aria-label="用户列表">
          <h3 class="section-title section-title-sm">用户列表</h3>
          <div v-if="loading" class="page-loading">载入中...</div>
          <div v-else-if="!hasRows" class="empty-state">暂无用户数据（后端 user 表）</div>
          <div v-else class="user-list-shell">
            <div class="user-list-head">
              <span>用户</span>
              <span>所属单位</span>
              <span>角色</span>
              <span class="col-right">操作</span>
            </div>
            <transition-group name="user-row-pop" tag="ul" class="user-list-rows">
              <li v-for="row in rows" :key="row.id" class="user-list-row">
                <div class="user-col user-col-user">
                  <div class="user-mainline">
                    <span class="user-avatar">{{ row.username ? row.username.slice(0, 1).toUpperCase() : '?' }}</span>
                    <div class="user-texts">
                      <div class="user-item-name">
                        {{ row.username }}
                        <span v-if="row.is_current_user" class="current-tag">当前登录</span>
                      </div>
                      <span class="user-item-id">ID #{{ row.id }}</span>
                    </div>
                  </div>
                </div>

                <div class="user-col user-col-role">
                  <span class="organization-tag">{{ row.organization || '-' }}</span>
                </div>

                <div class="user-col user-col-role">
                  <span :class="row.role === 'admin' ? 'role-admin' : 'role-user'">
                    {{ roleText(row.role) }}
                  </span>
                </div>

                <div class="user-col user-col-actions">
                  <button v-if="canManage" type="button" class="btn-detail"
                    :disabled="row.is_current_user || editingUserId !== null" @click="startEdit(row)">
                    编辑信息
                  </button>
                  <button v-if="canManage" type="button" class="btn-detail"
                    :disabled="updatingUserId === row.id || editingUserId !== null || (row.is_current_user && row.role === 'admin')"
                    @click="toggleRole(row)">
                    {{ updatingUserId === row.id ? '更新中...' : (row.role === 'admin' ? '降为普通用户' : '设为管理员') }}
                  </button>
                  <button v-if="canManage" type="button" class="btn-delete"
                    :disabled="deletingUserId === row.id || editingUserId !== null || row.is_current_user"
                    @click="removeUser(row)">
                    {{ deletingUserId === row.id ? '删除中...' : '删除' }}
                  </button>
                </div>
              </li>
            </transition-group>
          </div>
        </div>
      </section>

      <section v-else class="user-self-layout" aria-label="个人中心主体">
        <div class="card-surface self-profile-card">
          <div class="profile-card-head">
            <span class="profile-avatar">{{ currentUsername.slice(0, 1).toUpperCase() }}</span>
            <div class="profile-head-texts">
              <h3 class="section-title section-title-sm">个人信息卡</h3>
              <div class="profile-username">{{ currentUsername }}</div>
              <div class="profile-meta">
                <span class="profile-tag">{{ currentRoleText }}</span>
                <span class="profile-tag">{{ currentUserRow?.organization || '未填写单位' }}</span>
              </div>
            </div>
          </div>

          <p class="user-page-subtitle" style="margin-top: 0;">
            仅管理当前登录账号信息，保存后即时生效。
          </p>

          <form class="self-profile-form" @submit.prevent="saveCurrentUserProfile">
            <label class="field-block">
              <span>用户名</span>
              <input v-model.trim="selfForm.username" maxlength="50" minlength="3" required>
            </label>
            <label class="field-block">
              <span>所属单位</span>
              <input v-model.trim="selfForm.organization" maxlength="120" required placeholder="例如：XX 环卫中心">
            </label>
            <label class="field-block">
              <span>新密码（留空不修改）</span>
              <input v-model="selfForm.password" type="password" minlength="6" placeholder="至少 6 位">
            </label>
            <label class="field-block">
              <span>确认新密码</span>
              <input v-model="selfForm.confirm_password" type="password" minlength="6" placeholder="再次输入新密码">
            </label>
            <div class="create-actions">
              <button type="submit" :disabled="selfSubmitting">
                {{ selfSubmitting ? '保存中...' : '保存我的信息' }}
              </button>
            </div>
          </form>
        </div>

        <div class="card-surface self-assets-card">
          <div class="assets-head">
            <h3 class="section-title section-title-sm">我的机器人与任务</h3>
            <button type="button" class="self-square-btn" :disabled="selfAssetsLoading" @click="loadSelfAssets">
              {{ selfAssetsLoading ? '刷新中...' : '刷新' }}
            </button>
          </div>

          <div class="self-overview-grid" v-if="currentUserRow">
            <div class="overview-item">
              <span class="overview-label">用户 ID</span>
              <span class="overview-value">#{{ currentUserRow.id }}</span>
            </div>
            <div class="overview-item">
              <span class="overview-label">用户名</span>
              <span class="overview-value">{{ currentUserRow.username || '-' }}</span>
            </div>
          </div>

          <div class="asset-section">
            <div class="asset-section-head">
              <h4>我的机器人</h4>
              <RouterLink to="/robot" class="self-square-btn">打开机器人管理</RouterLink>
            </div>
            <div v-if="selfAssetsLoading" class="page-loading">载入中...</div>
            <div v-else-if="!hasMyRobots" class="empty-state">你还没有绑定机器人</div>
            <ul v-else class="asset-list">
              <li v-for="robot in myRobots" :key="`robot-${robot.id}`" class="asset-item">
                <div class="asset-main">
                  <div class="asset-title">{{ robot.name || '未命名机器人' }}</div>
                  <div class="asset-meta">设备ID：{{ robot.device_id || '-' }} · 状态：{{ robot.status || '-' }}</div>
                </div>
                <div class="asset-actions">
                  <RouterLink class="self-square-btn" :to="`/robot/${robot.id}`">进入控制</RouterLink>
                  <button
                    type="button"
                    class="self-square-btn self-square-btn-danger"
                    :disabled="robotOpsLoadingId === robot.id"
                    @click="deleteMyRobot(robot)">
                    {{ robotOpsLoadingId === robot.id ? '删除中...' : '删除' }}
                  </button>
                </div>
              </li>
            </ul>
          </div>

          <div class="asset-section">
            <div class="asset-section-head">
              <h4>我的巡检任务</h4>
              <RouterLink to="/result" class="self-square-btn">查看检测任务</RouterLink>
            </div>
            <div v-if="selfAssetsLoading" class="page-loading">载入中...</div>
            <div v-else-if="!hasMyPatrolTasks" class="empty-state">暂无巡检任务</div>
            <ul v-else class="asset-list">
              <li v-for="task in myPatrolTasks" :key="`task-${task.id}`" class="asset-item">
                <div class="asset-main">
                  <div class="asset-title">{{ task.name || `任务 #${task.id}` }}</div>
                  <div class="asset-meta">状态：{{ patrolStatusText(task.status) }} · 机器人ID：#{{ task.robot_id }} · 创建：{{ formatDateTime(task.created_at) }}</div>
                </div>
                <div class="asset-actions">
                  <button
                    type="button"
                    class="self-square-btn"
                    :disabled="patrolOpsLoadingId === task.id || String(task.status || '').toUpperCase() === 'RUNNING'"
                    @click="setMyPatrolTaskStatus(task, 'RUNNING')">
                    运行
                  </button>
                  <button
                    type="button"
                    class="self-square-btn"
                    :disabled="patrolOpsLoadingId === task.id || String(task.status || '').toUpperCase() === 'PAUSED'"
                    @click="setMyPatrolTaskStatus(task, 'PAUSED')">
                    暂停
                  </button>
                  <button
                    type="button"
                    class="self-square-btn self-square-btn-danger"
                    :disabled="patrolOpsLoadingId === task.id"
                    @click="deleteMyPatrolTask(task)">
                    {{ patrolOpsLoadingId === task.id ? '处理中...' : '删除' }}
                  </button>
                </div>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <transition name="edit-modal-fade">
        <div v-if="editingUserId !== null" class="edit-modal-mask" @click.self="cancelEdit">
          <section class="edit-modal-card card-surface" aria-label="编辑用户信息卡片">
            <h3 class="section-title section-title-sm">编辑成员信息</h3>
            <p class="user-page-subtitle" style="margin-top: 0;">
              用户 ID #{{ editingUserId }} · 当前用户名：{{ editingRowName || '-' }}
            </p>
            <form class="edit-form-grid" @submit.prevent="saveUserProfile">
              <label class="field-block">
                <span>用户名</span>
                <input v-model.trim="editForm.username" maxlength="50" minlength="3" required>
              </label>
              <label class="field-block">
                <span>所属单位</span>
                <input v-model.trim="editForm.organization" maxlength="120" required placeholder="例如：XX 环卫中心">
              </label>
              <label class="field-block">
                <span>新密码（留空则不修改）</span>
                <input v-model="editForm.password" type="password" minlength="6" placeholder="至少 6 位">
              </label>
              <label class="field-block">
                <span>确认新密码</span>
                <input v-model="editForm.confirm_password" type="password" minlength="6" placeholder="再次输入新密码">
              </label>
              <p class="user-page-subtitle" style="margin-top: -2px;">如不需要重置密码，请保持新密码和确认新密码为空。</p>
              <div class="edit-actions">
                <button type="submit" :disabled="savingProfileUserId !== null">
                  {{ savingProfileUserId !== null ? '保存中...' : '保存修改' }}
                </button>
                <button type="button" :disabled="savingProfileUserId !== null" @click="cancelEdit">
                  取消
                </button>
              </div>
            </form>
          </section>
        </div>
      </transition>
    </div>
  </div>
</template>

<style scoped>
.user-admin-body {
  display: grid;
  gap: 14px;
}

.user-page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px;
  border-radius: 12px;
  border: 1px solid rgba(20, 110, 89, 0.22);
  background: linear-gradient(145deg, rgba(245, 252, 249, 0.88), rgba(229, 245, 238, 0.78));
}

.user-page-subtitle {
  margin: 6px 0 0;
  color: #4d766d;
  font-size: 12px;
}

.head-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.login-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  border: 1px solid rgba(22, 116, 93, 0.34);
  padding: 6px 10px;
  color: #145647;
  background: rgba(255, 255, 255, 0.76);
  font-size: 12px;
  font-weight: 700;
}

.error-banner {
  border-radius: 10px;
  border: 1px solid rgba(185, 57, 70, 0.38);
  background: rgba(251, 235, 237, 0.92);
  color: #8a2e39;
  padding: 10px 12px;
  font-size: 13px;
}

.user-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.summary-item {
  border-radius: 12px;
  padding: 14px;
  border: 1px solid rgba(27, 110, 88, 0.16);
  background: linear-gradient(160deg, rgba(245, 252, 249, 0.9), rgba(237, 249, 244, 0.72));
  box-shadow: 0 8px 18px rgba(31, 109, 90, 0.08);
}

.summary-label {
  font-size: 12px;
  color: #4d766d;
}

.summary-value {
  margin-top: 6px;
  font-size: 22px;
  font-weight: 800;
  color: #17463d;
}

.user-main-grid {
  display: grid;
  grid-template-columns: minmax(280px, 0.9fr) minmax(0, 1.5fr);
  gap: 12px;
  align-items: start;
}

.user-self-layout {
  display: grid;
  grid-template-columns: minmax(300px, 1.05fr) minmax(260px, 0.95fr);
  gap: 12px;
  align-items: start;
}

.self-profile-card,
.self-assets-card {
  display: grid;
  gap: 10px;
}

.profile-card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px;
  border-radius: 12px;
  border: 1px solid rgba(20, 108, 88, 0.14);
  background: linear-gradient(145deg, rgba(244, 252, 248, 0.92), rgba(233, 246, 239, 0.82));
}

.profile-avatar {
  width: 44px;
  height: 44px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 800;
  color: #125745;
  border: 1px solid rgba(18, 110, 89, 0.25);
  background: radial-gradient(circle at 30% 30%, rgba(255, 255, 255, 0.95), rgba(182, 230, 211, 0.95));
}

.profile-head-texts {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.profile-username {
  font-size: 14px;
  font-weight: 700;
  color: #184d42;
}

.profile-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.profile-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  color: #2c6257;
  background: rgba(94, 157, 139, 0.18);
}

.self-profile-form {
  display: grid;
  gap: 10px;
}

.assets-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.asset-section {
  border: 1px solid rgba(20, 108, 88, 0.14);
  border-radius: 12px;
  background: rgba(248, 253, 250, 0.76);
  padding: 10px;
  display: grid;
  gap: 8px;
}

.asset-section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.asset-section-head h4 {
  margin: 0;
  font-size: 14px;
  color: #184d42;
}

.asset-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 8px;
}

.asset-item {
  border-radius: 10px;
  border: 1px solid rgba(20, 108, 88, 0.14);
  background: rgba(255, 255, 255, 0.92);
  padding: 10px;
  display: grid;
  gap: 8px;
}

.asset-main {
  display: grid;
  gap: 4px;
}

.asset-title {
  font-size: 13px;
  font-weight: 700;
  color: #184d42;
}

.asset-meta {
  font-size: 12px;
  color: #58786f;
  line-height: 1.45;
}

.asset-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.self-square-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: linear-gradient(145deg, #158966, #136f80);
  color: #ffffff;
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
  transition: transform 0.16s ease, box-shadow 0.16s ease, filter 0.16s ease;
}

.self-square-btn:hover {
  transform: translateY(-1px);
  filter: brightness(1.02);
  box-shadow: 0 8px 16px rgba(20, 99, 88, 0.22);
}

.self-square-btn:disabled {
  opacity: 0.64;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.self-square-btn-danger {
  background: linear-gradient(145deg, #bf4f45, #9f3f37);
}

.self-square-btn-danger:hover {
  box-shadow: 0 8px 16px rgba(159, 63, 55, 0.24);
}

.self-overview-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.overview-item {
  display: grid;
  gap: 3px;
  padding: 10px;
  border-radius: 10px;
  border: 1px solid rgba(20, 108, 88, 0.14);
  background: linear-gradient(150deg, rgba(248, 253, 250, 0.94), rgba(239, 249, 244, 0.88));
}

.overview-label {
  font-size: 11px;
  color: #5f7c75;
}

.overview-value {
  font-size: 14px;
  font-weight: 700;
  color: #184d42;
}

.self-tips {
  border-radius: 10px;
  padding: 10px;
  border: 1px dashed rgba(27, 110, 88, 0.28);
  background: rgba(246, 252, 249, 0.9);
}

.tip-title {
  font-size: 12px;
  font-weight: 700;
  color: #1a5b4d;
  margin-bottom: 4px;
}

.self-tips p {
  margin: 0;
  font-size: 12px;
  color: #4d766d;
}

.user-create,
.user-list {
  display: grid;
  gap: 10px;
}

.card-surface {
  border-radius: 12px;
  border: 1px solid rgba(27, 110, 88, 0.16);
  background: rgba(255, 255, 255, 0.92);
  padding: 12px;
  box-shadow: 0 10px 24px rgba(35, 105, 88, 0.08);
}

.create-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}

.create-actions {
  display: flex;
  align-items: end;
}

.edit-form-grid {
  display: grid;
  gap: 10px;
}

.edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.user-list-shell {
  display: grid;
  gap: 8px;
  border: 1px solid rgba(26, 113, 91, 0.14);
  border-radius: 12px;
  background: rgba(247, 253, 250, 0.66);
  padding: 8px;
}

.user-list-head {
  display: grid;
  grid-template-columns: minmax(180px, 1.1fr) minmax(170px, 1fr) minmax(120px, 0.7fr) minmax(220px, 1fr);
  gap: 10px;
  padding: 8px 12px;
  color: #5c7b72;
  font-size: 12px;
  font-weight: 700;
  border-radius: 10px;
  background: linear-gradient(160deg, rgba(232, 247, 240, 0.82), rgba(243, 252, 248, 0.72));
}

.col-right {
  text-align: right;
}

.user-list-rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}

.user-list-row {
  display: grid;
  grid-template-columns: minmax(180px, 1.1fr) minmax(170px, 1fr) minmax(120px, 0.7fr) minmax(220px, 1fr);
  gap: 10px;
  align-items: center;
  border-radius: 10px;
  border: 1px solid rgba(21, 116, 92, 0.2);
  background: linear-gradient(155deg, rgba(255, 255, 255, 0.96), rgba(244, 252, 248, 0.9));
  padding: 12px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.user-list-row:hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 22px rgba(17, 113, 89, 0.16);
}

.user-col {
  min-width: 0;
}

.edit-modal-mask {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: grid;
  place-items: center;
  padding: 18px;
  background: rgba(6, 31, 25, 0.35);
  backdrop-filter: blur(2px);
}

.edit-modal-card {
  width: min(560px, 100%);
  display: grid;
  gap: 10px;
  border-radius: 14px;
  border: 1px solid rgba(20, 109, 88, 0.26);
  box-shadow: 0 18px 44px rgba(10, 60, 49, 0.24);
}

.edit-modal-fade-enter-active,
.edit-modal-fade-leave-active {
  transition: opacity 180ms ease;
}

.edit-modal-fade-enter-from,
.edit-modal-fade-leave-to {
  opacity: 0;
}

.user-item-name {
  color: #184d42;
  font-weight: 800;
  display: flex;
  align-items: center;
  gap: 6px;
}

.user-item-id {
  font-size: 12px;
  color: #5e7c74;
}

.user-mainline {
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-texts {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.edit-inline-block {
  display: grid;
  gap: 4px;
}

.edit-input {
  width: 100%;
  min-height: 32px;
  border-radius: 8px;
}

.user-avatar {
  width: 34px;
  height: 34px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 800;
  color: #125745;
  background: radial-gradient(circle at 30% 30%, rgba(255, 255, 255, 0.9), rgba(182, 230, 211, 0.92));
  border: 1px solid rgba(18, 110, 89, 0.25);
}

.current-tag {
  margin-left: 6px;
  font-size: 10px;
  color: #0e5f4d;
  background: rgba(16, 127, 100, 0.14);
  border-radius: 999px;
  padding: 2px 8px;
}

.role-admin,
.role-user {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 700;
}

.organization-tag {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 700;
  color: #2a6256;
  background: rgba(110, 177, 158, 0.18);
}

.role-admin {
  color: #0f5a46;
  background: rgba(23, 144, 111, 0.18);
}

.role-user {
  color: #6a522f;
  background: rgba(214, 152, 71, 0.18);
}

.user-col-actions .btn-detail,
.user-col-actions .btn-delete {
  min-height: 34px;
  padding: 0 12px;
}

.user-row-pop-enter-active {
  animation: user-row-pop 320ms ease;
}

@keyframes user-row-pop {
  from {
    opacity: 0;
    transform: translateY(8px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (max-width: 980px) {

  .user-summary,
  .user-main-grid,
  .user-self-layout {
    grid-template-columns: 1fr;
  }

  .user-list-head {
    display: none;
  }

  .user-list-row {
    grid-template-columns: 1fr;
  }

  .user-col-actions {
    justify-content: flex-start;
  }

  .self-overview-grid {
    grid-template-columns: 1fr;
  }
}
</style>
