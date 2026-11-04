<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getJson } from '../lib/api'
import { confirmAndDeleteTask } from '../composables/useResultTaskActions'
import { pushFlash } from '../stores/session'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const task = ref(null)
const items = ref([])
const canDelete = ref(false)
const imageSize = ref('md')
const taskId = computed(() => route.params.id)

async function loadDetail() {
  loading.value = true
  try {
    const payload = await getJson(`/api/web/tasks/${taskId.value}`)
    task.value = payload.task
    items.value = payload.items || []
    canDelete.value = Boolean(payload.can_delete)
  } catch (error) {
    pushFlash(error.message || '任务详情加载失败', 'error')
  } finally {
    loading.value = false
  }
}

async function deleteTask() {
  await confirmAndDeleteTask(taskId.value, {
    onSuccess: async () => {
      await router.replace('/result')
    },
  })
}

watch(() => route.params.id, loadDetail)
onMounted(loadDetail)
</script>

<template>
  <div class="panel page-panel">
    <div class="panel-title">任务 #{{ task?.id || route.params.id }} 详情</div>
    <div class="panel-body text-secondary">
      <div v-if="loading" class="page-loading">载入中...</div>
      <template v-else-if="task">
        <div v-if="canDelete" style="margin-bottom:12px;">
          <button type="button" class="btn-delete" @click="deleteTask">删除当前检测结果</button>
        </div>
        <p>来源: {{ task.source_type }} | 设备: {{ task.device_id || '-' }} | 状态: {{ task.status }}</p>
        <p>位置: {{ task.display_location }}</p>
        <p>创建时间: {{ task.created_at }}</p>
        <hr>
        <div>
          <h4 class="section-title">识别结果</h4>
          <ul v-if="items.length" class="detail-list">
            <li v-for="item in items" :key="item.id">
              Label: {{ item.label }} | 置信度: {{ Number(item.confidence || 0).toFixed(2) }} | 处理状态: {{ item.handle_state
              }}
            </li>
          </ul>
          <p v-else class="text-muted">尚无识别项。</p>
        </div>
        <hr>
        <div class="image-size-controls">
          <span class="image-size-label">图片大小</span>
          <button type="button" class="image-size-btn" :class="{ active: imageSize === 'md' }"
            @click="imageSize = 'md'">中</button>
          <button type="button" class="image-size-btn" :class="{ active: imageSize === 'sm' }"
            @click="imageSize = 'sm'">小</button>
          <button type="button" class="image-size-btn" :class="{ active: imageSize === 'lg' }"
            @click="imageSize = 'lg'">大</button>
        </div>
        <div id="detailImageGrid" class="detail-image-grid" :class="`size-${imageSize}`">
          <div v-if="task.source_path" class="detail-image-col">
            <div class="section-title section-title-sm">原始图片</div>
            <img :src="`/${task.source_path}`" class="preview-image" alt="任务原始图片">
          </div>
          <div v-if="task.result_path" class="detail-image-col">
            <div class="section-title section-title-sm">识别后图片</div>
            <img :src="`/${task.result_path}`" class="preview-image" alt="任务识别结果图片">
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
