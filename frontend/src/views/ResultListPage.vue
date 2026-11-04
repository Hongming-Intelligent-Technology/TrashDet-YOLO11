<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getJson } from '../lib/api'
import { confirmAndDeleteTask } from '../composables/useResultTaskActions'
import { pushFlash } from '../stores/session'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const rows = ref([])
const pagination = ref(null)
const canDelete = ref(false)

const currentPage = computed(() => Number(route.query.page || 1))

function buildListEndpoint(page) {
  return `/api/web/tasks?page=${page}`
}

function buildRouteTarget(page) {
  return { name: 'results', query: { page } }
}

async function loadRows() {
  loading.value = true
  try {
    const endpoint = buildListEndpoint(currentPage.value)
    const payload = await getJson(endpoint)
    rows.value = payload.tasks || []
    pagination.value = payload.pagination || null
    canDelete.value = Boolean(payload.can_delete)
  } catch (error) {
    pushFlash(error.message || '任务视图加载失败', 'error')
  } finally {
    loading.value = false
  }
}

async function deleteTask(taskId) {
  await confirmAndDeleteTask(taskId, {
    onSuccess: loadRows,
  })
}

function goPage(page) {
  router.push(buildRouteTarget(page))
}

watch(() => route.query.page, loadRows)
onMounted(loadRows)
</script>

<template>
  <div class="panel page-panel result-list-page">
    <div class="panel-title">检测结果</div>
    <div class="panel-body">
      <div v-if="loading" class="page-loading">载入中...</div>
      <template v-else>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>上传机器人</th>
                <th>设备ID</th>
                <th>状态</th>
                <th>位置</th>
                <th>时间</th>
                <th class="col-center">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="task in rows" :key="`task-${task.id}`">
                <td>{{ task.id }}</td>
                <td>{{ task.source_type || '-' }}</td>
                <td>{{ task.device_id || '-' }}</td>
                <td>{{ task.status || '-' }}</td>
                <td>{{ task.display_location || task.location || '-' }}</td>
                <td>{{ task.created_at || '-' }}</td>
                <td class="col-center col-nowrap">
                  <RouterLink class="btn-detail result-list-square-btn" :to="`/result/${task.id}`">详情</RouterLink>
                  <button v-if="canDelete" type="button" class="btn-delete" style="margin-left:6px;" @click="deleteTask(task.id)">删除</button>
                </td>
              </tr>
              <tr v-if="!rows.length">
                <td :colspan="7" class="empty-state">暂无任务数据</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="pagination" class="pagination-line">
          <a v-if="pagination.has_prev" class="link-inline" href="#" @click.prevent="goPage(pagination.prev_num)">上一页</a>
          &nbsp; 第 {{ pagination.page }} 页 &nbsp;
          <a v-if="pagination.has_next" class="link-inline" href="#" @click.prevent="goPage(pagination.next_num)">下一页</a>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.result-list-page .result-list-square-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 38px;
  padding: 0 12px;
  border-radius: 6px;
  text-decoration: none;
}
</style>
