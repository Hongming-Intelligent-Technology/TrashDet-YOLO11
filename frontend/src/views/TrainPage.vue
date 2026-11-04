<script setup>
import { onBeforeUnmount, reactive, ref } from 'vue'
import { getJson, postForm } from '../lib/api'
import { pushFlash } from '../stores/session'

const datasetZip = ref(null)
const weightFile = ref(null)
const loading = ref(false)
const polling = ref(false)
const datasetInput = ref(null)
const weightInput = ref(null)
const currentJob = ref(null)
const trainMaxBytes = ref(null)
let pollingTimer = null

const form = reactive({
  dataYaml: 'data.yaml',
  epochs: 50,
  batch: 8,
  imgsz: 640,
  device: 'cpu',
  runName: '',
  resume: false,
})

function hasAllowedExtension(file, expectedExt) {
  const ext = file?.name?.split('.').pop()?.toLowerCase()
  return ext === expectedExt
}

function formatBytes(bytes) {
  const value = Number(bytes || 0)
  if (!Number.isFinite(value) || value <= 0) {
    return ''
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let index = 0
  let size = value
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024
    index += 1
  }
  return `${size.toFixed(size >= 10 || index === 0 ? 0 : 1)} ${units[index]}`
}

async function loadTrainConfig() {
  try {
    const payload = await getJson('/api/train/config')
    const sizeLimit = payload?.limits?.train_max_content_length
    trainMaxBytes.value = Number.isFinite(Number(sizeLimit)) ? Number(sizeLimit) : null
  } catch {
    trainMaxBytes.value = null
  }
}

function chooseDataset(file) {
  if (!file) {
    return
  }
  if (!hasAllowedExtension(file, 'zip')) {
    pushFlash('数据集只支持 ZIP 文件', 'error')
    return
  }
  if (trainMaxBytes.value && file.size > trainMaxBytes.value) {
    pushFlash(`数据集大小超过上限（${formatBytes(trainMaxBytes.value)}）`, 'error')
    return
  }
  datasetZip.value = file
}

function chooseWeight(file) {
  if (!file) {
    weightFile.value = null
    return
  }

  if (!hasAllowedExtension(file, 'pt')) {
    pushFlash('权重文件只支持 .pt', 'error')
    return
  }

  weightFile.value = file
}

function resetForm() {
  datasetZip.value = null
  weightFile.value = null
  form.dataYaml = 'data.yaml'
  form.epochs = 50
  form.batch = 8
  form.imgsz = 640
  form.device = 'cpu'
  form.runName = ''
  form.resume = false

  if (datasetInput.value) {
    datasetInput.value.value = ''
  }
  if (weightInput.value) {
    weightInput.value.value = ''
  }
}

async function refreshActiveJobStatus() {
  try {
    const payload = await getJson('/api/train/status')
    currentJob.value = payload.job || null
    if (currentJob.value) {
      startPolling(currentJob.value.job_id)
    }
  } catch {
    // Keep UI usable even when status endpoint is temporarily unavailable.
  }
}

async function fetchStatus(jobId, showError = false) {
  try {
    const payload = await getJson(`/api/train/status/${jobId}`)
    currentJob.value = payload.job
    const status = payload.job?.status
    if (status === 'completed' || status === 'failed') {
      stopPolling()
      polling.value = false
      if (status === 'completed') {
        pushFlash('训练任务已完成', 'success')
      } else if (payload.job?.error && showError) {
        pushFlash(payload.job.error, 'error')
      }
    }
  } catch (error) {
    if (showError) {
      pushFlash(error.message || '训练状态获取失败', 'error')
    }
  }
}

function stopPolling() {
  if (pollingTimer) {
    window.clearInterval(pollingTimer)
    pollingTimer = null
  }
}

function startPolling(jobId) {
  stopPolling()
  polling.value = true
  pollingTimer = window.setInterval(() => {
    fetchStatus(jobId)
  }, 2500)
}

async function submitTraining() {
  if (!datasetZip.value) {
    pushFlash('请先上传标注数据集 ZIP 文件', 'warning')
    return
  }

  loading.value = true
  try {
    const formData = new FormData()
    formData.append('dataset_zip', datasetZip.value)
    formData.append('data_yaml', form.dataYaml)
    formData.append('epochs', String(form.epochs))
    formData.append('batch', String(form.batch))
    formData.append('imgsz', String(form.imgsz))
    formData.append('device', form.device)
    formData.append('run_name', form.runName)
    formData.append('resume', String(form.resume))
    if (weightFile.value) {
      formData.append('weight_file', weightFile.value)
    }

    const payload = await postForm('/api/train/start', formData)
    currentJob.value = {
      job_id: payload.job_id,
      status: payload.status,
      logs: ['任务已提交，等待服务器启动训练...'],
      meta: {
        data_yaml: form.dataYaml,
      },
    }
    startPolling(payload.job_id)
    await fetchStatus(payload.job_id)
    pushFlash(payload.message || '训练任务已启动', 'success')
  } catch (error) {
    pushFlash(error.message || '启动训练失败', 'error')
  } finally {
    loading.value = false
  }
}

onBeforeUnmount(() => {
  stopPolling()
})

refreshActiveJobStatus()
loadTrainConfig()
</script>

<template>
  <div class="panel page-panel">
    <div class="panel-title">继续训练</div>
    <div class="panel-body text-secondary">
      <div class="upload-layout">
        <div class="upload-col upload-control-col">
          <div class="upload-card">
            <div class="section-title section-title-sm">1. 上传标注数据集</div>
            <p v-if="trainMaxBytes" class="text-muted" style="margin:0 0 8px;">当前上传上限：{{ formatBytes(trainMaxBytes) }}
            </p>
            <div class="upload-drop-area" @click="datasetInput?.click()">
              {{ datasetZip ? `已选择: ${datasetZip.name}` : '点击选择 ZIP 数据集（含 images/labels 与 data.yaml）' }}
            </div>
            <input ref="datasetInput" class="hidden" type="file" accept=".zip,application/zip"
              @change="chooseDataset($event.target.files?.[0])">
          </div>

          <div class="upload-card">
            <div class="section-title section-title-sm">2. 可选上传基础权重</div>
            <div class="upload-drop-area" @click="weightInput?.click()">
              {{ weightFile ? `已选择: ${weightFile.name}` : '点击选择 .pt 权重（不选则使用后端默认 YOLO_MODEL_PATH）' }}
            </div>
            <input ref="weightInput" class="hidden" type="file" accept=".pt"
              @change="chooseWeight($event.target.files?.[0])">
          </div>
        </div>

        <div class="upload-col upload-preview-col">
          <div class="upload-card">
            <div class="section-title section-title-sm">3. 训练参数</div>

            <div class="form-row mt-8">
              <input v-model.trim="form.dataYaml" class="input-control" placeholder="data.yaml 路径（默认 data.yaml）">
              <input v-model.number="form.epochs" class="input-control" type="number" min="1" max="10000"
                placeholder="epochs">
            </div>
            <div class="form-row mt-8">
              <input v-model.number="form.batch" class="input-control" type="number" min="1" max="256"
                placeholder="batch">
              <input v-model.number="form.imgsz" class="input-control" type="number" min="64" max="4096"
                placeholder="imgsz">
            </div>
            <div class="form-row mt-8">
              <input v-model.trim="form.device" class="input-control" placeholder="device，例如 cpu 或 0">
              <input v-model.trim="form.runName" class="input-control" placeholder="run 名称（可选）">
            </div>
            <div class="form-row mt-8">
              <label><input v-model="form.resume" type="checkbox"> 恢复训练（resume）</label>
            </div>

            <div class="button-row mt-10">
              <button type="button" :disabled="loading" @click="submitTraining">
                {{ loading ? '提交中...' : '开始继续训练' }}
              </button>
              <button type="button" @click="resetForm">重置表单</button>
              <button v-if="currentJob?.job_id" type="button" :disabled="loading"
                @click="fetchStatus(currentJob.job_id, true)">
                刷新状态
              </button>
            </div>
          </div>

          <div class="upload-card">
            <div class="section-title section-title-sm">任务状态</div>
            <div v-if="currentJob">
              <p>任务ID：{{ currentJob.job_id }}</p>
              <p>状态：{{ currentJob.status }}</p>
              <p v-if="currentJob.created_at">创建时间：{{ currentJob.created_at }}</p>
              <p v-if="currentJob.started_at">启动时间：{{ currentJob.started_at }}</p>
              <p v-if="currentJob.completed_at">完成时间：{{ currentJob.completed_at }}</p>
              <p v-if="currentJob.error" style="color:#ff6363;">错误：{{ currentJob.error }}</p>
              <p v-if="currentJob.result?.save_dir">输出目录：{{ currentJob.result.save_dir }}</p>
              <p v-if="polling && currentJob.status !== 'completed' && currentJob.status !== 'failed'">轮询中：每 2.5 秒自动刷新
              </p>
            </div>
            <div v-else class="text-muted">暂无训练任务</div>
          </div>

          <div class="upload-card">
            <div class="section-title section-title-sm">训练日志（最近 40 行）</div>
            <div class="table-wrap max-h-520">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>日志</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(line, idx) in currentJob?.logs || []" :key="`${idx}-${line}`">
                    <td>{{ line }}</td>
                  </tr>
                  <tr v-if="!(currentJob?.logs || []).length">
                    <td class="empty-state">暂无日志</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>