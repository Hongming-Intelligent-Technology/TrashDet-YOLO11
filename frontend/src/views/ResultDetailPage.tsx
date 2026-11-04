import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { errorMessage, getJson } from '../lib/api'
import { confirmAndDeleteTask } from '../lib/resultTaskActions'
import { pushFlash } from '../stores/session'
import type { DetectItemRow, TaskRow } from '../types'

interface TaskDetailResponse {
  task?: TaskRow | null
  items?: DetectItemRow[]
  can_delete?: boolean
}

type ImageSize = 'sm' | 'md' | 'lg'

const IMAGE_SIZE_BUTTONS: Array<{ size: ImageSize; label: string }> = [
  { size: 'md', label: '中' },
  { size: 'sm', label: '小' },
  { size: 'lg', label: '大' },
]

export default function ResultDetailPage() {
  const navigate = useNavigate()
  const { id: taskId = '' } = useParams()
  const [loading, setLoading] = useState(false)
  const [task, setTask] = useState<TaskRow | null>(null)
  const [items, setItems] = useState<DetectItemRow[]>([])
  const [canDelete, setCanDelete] = useState(false)
  const [imageSize, setImageSize] = useState<ImageSize>('md')

  const loadDetail = useCallback(async () => {
    setLoading(true)
    try {
      const payload = await getJson<TaskDetailResponse>(`/api/web/tasks/${taskId}`)
      setTask(payload.task || null)
      setItems(payload.items || [])
      setCanDelete(Boolean(payload.can_delete))
    } catch (error) {
      pushFlash(errorMessage(error, '任务详情加载失败'), 'error')
    } finally {
      setLoading(false)
    }
  }, [taskId])

  useEffect(() => {
    loadDetail()
  }, [loadDetail])

  function deleteTask() {
    confirmAndDeleteTask(taskId, {
      onSuccess: () => {
        navigate('/result', { replace: true })
      },
    })
  }

  return (
    <div className="panel page-panel">
      <div className="panel-title">任务 #{task?.id || taskId} 详情</div>
      <div className="panel-body text-secondary">
        {loading ? (
          <div className="page-loading">载入中...</div>
        ) : task ? (
          <>
            {canDelete && (
              <div style={{ marginBottom: 12 }}>
                <button type="button" className="btn-delete" onClick={deleteTask}>删除当前检测结果</button>
              </div>
            )}
            <p>来源: {task.source_type} | 设备: {task.device_id || '-'} | 状态: {task.status}</p>
            <p>位置: {task.display_location}</p>
            <p>创建时间: {task.created_at}</p>
            <hr />
            <div>
              <h4 className="section-title">识别结果</h4>
              {items.length ? (
                <ul className="detail-list">
                  {items.map((item) => (
                    <li key={item.id}>
                      Label: {item.label} | 置信度: {Number(item.confidence || 0).toFixed(2)} | 处理状态: {item.handle_state}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted">尚无识别项。</p>
              )}
            </div>
            <hr />
            <div className="image-size-controls">
              <span className="image-size-label">图片大小</span>
              {IMAGE_SIZE_BUTTONS.map(({ size, label }) => (
                <button
                  key={size}
                  type="button"
                  className={`image-size-btn${imageSize === size ? ' active' : ''}`}
                  onClick={() => setImageSize(size)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div id="detailImageGrid" className={`detail-image-grid size-${imageSize}`}>
              {task.source_path && (
                <div className="detail-image-col">
                  <div className="section-title section-title-sm">原始图片</div>
                  <img src={`/${task.source_path}`} className="preview-image" alt="任务原始图片" />
                </div>
              )}
              {task.result_path && (
                <div className="detail-image-col">
                  <div className="section-title section-title-sm">识别后图片</div>
                  <img src={`/${task.result_path}`} className="preview-image" alt="任务识别结果图片" />
                </div>
              )}
            </div>
          </>
        ) : null}
      </div>
    </div>
  )
}
