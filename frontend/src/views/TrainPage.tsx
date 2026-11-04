import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage, getJson, postForm } from '../lib/api'
import { fieldUpdater } from '../lib/forms'
import { pollWhileVisible } from '../lib/polling'
import { pushFlash } from '../stores/session'

interface TrainJob {
  job_id: string
  status?: string
  created_at?: string | null
  started_at?: string | null
  completed_at?: string | null
  error?: string | null
  result?: { save_dir?: string; weights_hint?: string } | null
  logs?: string[]
  meta?: Record<string, unknown>
}

interface TrainForm {
  [key: string]: unknown
  dataYaml: string
  epochs: string
  batch: string
  imgsz: string
  device: string
  runName: string
  resume: boolean
}

const DEFAULT_FORM: TrainForm = {
  dataYaml: 'data.yaml',
  epochs: '50',
  batch: '8',
  imgsz: '640',
  device: 'cpu',
  runName: '',
  resume: false,
}

const POLL_INTERVAL_MS = 2500

function hasAllowedExtension(file: File, expectedExt: string) {
  return file.name.split('.').pop()?.toLowerCase() === expectedExt
}

function formatBytes(bytes: number | null) {
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

function isFinished(status?: string) {
  return status === 'completed' || status === 'failed'
}

export default function TrainPage() {
  const [datasetZip, setDatasetZip] = useState<File | null>(null)
  const [weightFile, setWeightFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [polling, setPolling] = useState(false)
  const [currentJob, setCurrentJob] = useState<TrainJob | null>(null)
  const [trainMaxBytes, setTrainMaxBytes] = useState<number | null>(null)
  const [form, setForm] = useState<TrainForm>(DEFAULT_FORM)
  const update = fieldUpdater(setForm)

  const datasetInputRef = useRef<HTMLInputElement>(null)
  const weightInputRef = useRef<HTMLInputElement>(null)
  const stopPollingRef = useRef<(() => void) | null>(null)

  const stopPolling = useCallback(() => {
    stopPollingRef.current?.()
    stopPollingRef.current = null
  }, [])

  const fetchStatus = useCallback(async (jobId: string, showError = false) => {
    try {
      const payload = await getJson<{ job: TrainJob }>(`/api/train/status/${jobId}`)
      setCurrentJob(payload.job)
      const status = payload.job?.status
      if (isFinished(status)) {
        stopPolling()
        setPolling(false)
        if (status === 'completed') {
          pushFlash('训练任务已完成', 'success')
        } else if (payload.job?.error && showError) {
          pushFlash(payload.job.error, 'error')
        }
      }
    } catch (error) {
      if (showError) {
        pushFlash(errorMessage(error, '训练状态获取失败'), 'error')
      }
    }
  }, [stopPolling])

  const startPolling = useCallback((jobId: string) => {
    stopPolling()
    setPolling(true)
    stopPollingRef.current = pollWhileVisible(() => fetchStatus(jobId), POLL_INTERVAL_MS, { immediate: false })
  }, [fetchStatus, stopPolling])

  useEffect(() => {
    let cancelled = false

    getJson<{ job: TrainJob | null }>('/api/train/status')
      .then((payload) => {
        if (cancelled) return
        setCurrentJob(payload.job || null)
        // Only follow a job that is still running; a finished one is just displayed.
        if (payload.job && !isFinished(payload.job.status)) {
          startPolling(payload.job.job_id)
        }
      })
      .catch(() => {
        // Keep UI usable even when status endpoint is temporarily unavailable.
      })

    getJson<{ limits?: { train_max_content_length?: number | null } }>('/api/train/config')
      .then((payload) => {
        if (cancelled) return
        const sizeLimit = payload?.limits?.train_max_content_length
        setTrainMaxBytes(sizeLimit != null && Number.isFinite(Number(sizeLimit)) ? Number(sizeLimit) : null)
      })
      .catch(() => {
        if (!cancelled) setTrainMaxBytes(null)
      })

    return () => {
      cancelled = true
      stopPolling()
    }
  }, [startPolling, stopPolling])

  function chooseDataset(file: File | undefined) {
    if (!file) {
      return
    }
    if (!hasAllowedExtension(file, 'zip')) {
      pushFlash('数据集只支持 ZIP 文件', 'error')
      return
    }
    if (trainMaxBytes && file.size > trainMaxBytes) {
      pushFlash(`数据集大小超过上限（${formatBytes(trainMaxBytes)}）`, 'error')
      return
    }
    setDatasetZip(file)
  }

  function chooseWeight(file: File | undefined) {
    if (!file) {
      setWeightFile(null)
      return
    }
    if (!hasAllowedExtension(file, 'pt')) {
      pushFlash('权重文件只支持 .pt', 'error')
      return
    }
    setWeightFile(file)
  }

  function resetForm() {
    setDatasetZip(null)
    setWeightFile(null)
    setForm(DEFAULT_FORM)
    if (datasetInputRef.current) datasetInputRef.current.value = ''
    if (weightInputRef.current) weightInputRef.current.value = ''
  }

  async function submitTraining() {
    if (!datasetZip) {
      pushFlash('请先上传标注数据集 ZIP 文件', 'warning')
      return
    }

    setLoading(true)
    try {
      const formData = new FormData()
      formData.append('dataset_zip', datasetZip)
      formData.append('data_yaml', form.dataYaml.trim())
      formData.append('epochs', form.epochs)
      formData.append('batch', form.batch)
      formData.append('imgsz', form.imgsz)
      formData.append('device', form.device.trim())
      formData.append('run_name', form.runName.trim())
      formData.append('resume', String(form.resume))
      if (weightFile) {
        formData.append('weight_file', weightFile)
      }

      const payload = await postForm<{ job_id: string; status?: string; message?: string }>('/api/train/start', formData)
      setCurrentJob({
        job_id: payload.job_id,
        status: payload.status,
        logs: ['任务已提交，等待服务器启动训练...'],
        meta: { data_yaml: form.dataYaml.trim() },
      })
      startPolling(payload.job_id)
      await fetchStatus(payload.job_id)
      pushFlash(payload.message || '训练任务已启动', 'success')
    } catch (error) {
      pushFlash(errorMessage(error, '启动训练失败'), 'error')
    } finally {
      setLoading(false)
    }
  }

  const logs = currentJob?.logs || []

  return (
    <div className="panel page-panel">
      <div className="panel-title">继续训练</div>
      <div className="panel-body text-secondary">
        <div className="upload-layout">
          <div className="upload-col upload-control-col">
            <div className="upload-card">
              <div className="section-title section-title-sm">1. 上传标注数据集</div>
              {trainMaxBytes ? (
                <p className="text-muted" style={{ margin: '0 0 8px' }}>当前上传上限：{formatBytes(trainMaxBytes)}</p>
              ) : null}
              <div className="upload-drop-area" onClick={() => datasetInputRef.current?.click()}>
                {datasetZip ? `已选择: ${datasetZip.name}` : '点击选择 ZIP 数据集（含 images/labels 与 data.yaml）'}
              </div>
              <input
                ref={datasetInputRef}
                className="hidden"
                type="file"
                accept=".zip,application/zip"
                onChange={(event) => chooseDataset(event.target.files?.[0])}
              />
            </div>

            <div className="upload-card">
              <div className="section-title section-title-sm">2. 可选上传基础权重</div>
              <div className="upload-drop-area" onClick={() => weightInputRef.current?.click()}>
                {weightFile ? `已选择: ${weightFile.name}` : '点击选择 .pt 权重（不选则使用后端默认 YOLO_MODEL_PATH）'}
              </div>
              <input
                ref={weightInputRef}
                className="hidden"
                type="file"
                accept=".pt"
                onChange={(event) => chooseWeight(event.target.files?.[0])}
              />
            </div>
          </div>

          <div className="upload-col upload-preview-col">
            <div className="upload-card">
              <div className="section-title section-title-sm">3. 训练参数</div>

              <div className="form-row mt-8">
                <input value={form.dataYaml} onChange={update('dataYaml')} className="input-control" placeholder="data.yaml 路径（默认 data.yaml）" />
                <input value={form.epochs} onChange={update('epochs')} className="input-control" type="number" min={1} max={10000} placeholder="epochs" />
              </div>
              <div className="form-row mt-8">
                <input value={form.batch} onChange={update('batch')} className="input-control" type="number" min={1} max={256} placeholder="batch" />
                <input value={form.imgsz} onChange={update('imgsz')} className="input-control" type="number" min={64} max={4096} placeholder="imgsz" />
              </div>
              <div className="form-row mt-8">
                <input value={form.device} onChange={update('device')} className="input-control" placeholder="device，例如 cpu 或 0" />
                <input value={form.runName} onChange={update('runName')} className="input-control" placeholder="run 名称（可选）" />
              </div>
              <div className="form-row mt-8">
                <label>
                  <input checked={form.resume} onChange={update('resume')} type="checkbox" /> 恢复训练（resume）
                </label>
              </div>

              <div className="button-row mt-10">
                <button type="button" disabled={loading} onClick={submitTraining}>
                  {loading ? '提交中...' : '开始继续训练'}
                </button>
                <button type="button" onClick={resetForm}>重置表单</button>
                {currentJob?.job_id && (
                  <button type="button" disabled={loading} onClick={() => fetchStatus(currentJob.job_id, true)}>
                    刷新状态
                  </button>
                )}
              </div>
            </div>

            <div className="upload-card">
              <div className="section-title section-title-sm">任务状态</div>
              {currentJob ? (
                <div>
                  <p>任务ID：{currentJob.job_id}</p>
                  <p>状态：{currentJob.status}</p>
                  {currentJob.created_at && <p>创建时间：{currentJob.created_at}</p>}
                  {currentJob.started_at && <p>启动时间：{currentJob.started_at}</p>}
                  {currentJob.completed_at && <p>完成时间：{currentJob.completed_at}</p>}
                  {currentJob.error && <p style={{ color: '#ff6363' }}>错误：{currentJob.error}</p>}
                  {currentJob.result?.save_dir && <p>输出目录：{currentJob.result.save_dir}</p>}
                  {polling && !isFinished(currentJob.status) && <p>轮询中：每 2.5 秒自动刷新</p>}
                </div>
              ) : (
                <div className="text-muted">暂无训练任务</div>
              )}
            </div>

            <div className="upload-card">
              <div className="section-title section-title-sm">训练日志（最近 40 行）</div>
              <div className="table-wrap max-h-520">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>日志</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logs.map((line, idx) => (
                      <tr key={`${idx}-${line}`}>
                        <td>{line}</td>
                      </tr>
                    ))}
                    {!logs.length && (
                      <tr>
                        <td className="empty-state">暂无日志</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
