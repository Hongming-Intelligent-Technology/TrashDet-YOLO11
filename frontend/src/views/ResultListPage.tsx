import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { errorMessage, getJson } from '../lib/api'
import { confirmAndDeleteTask } from '../lib/resultTaskActions'
import { pushFlash } from '../stores/session'
import type { Pagination, TaskRow } from '../types'
import './ResultListPage.css'

interface TasksResponse {
  tasks?: TaskRow[]
  pagination?: Pagination | null
  can_delete?: boolean
}

export default function ResultListPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const currentPage = Number(searchParams.get('page') || 1)

  const [loading, setLoading] = useState(false)
  const [rows, setRows] = useState<TaskRow[]>([])
  const [pagination, setPagination] = useState<Pagination | null>(null)
  const [canDelete, setCanDelete] = useState(false)

  const loadRows = useCallback(async () => {
    setLoading(true)
    try {
      const payload = await getJson<TasksResponse>(`/api/web/tasks?page=${currentPage}`)
      setRows(payload.tasks || [])
      setPagination(payload.pagination || null)
      setCanDelete(Boolean(payload.can_delete))
    } catch (error) {
      pushFlash(errorMessage(error, '任务视图加载失败'), 'error')
    } finally {
      setLoading(false)
    }
  }, [currentPage])

  useEffect(() => {
    loadRows()
  }, [loadRows])

  function deleteTask(taskId: number) {
    confirmAndDeleteTask(taskId, { onSuccess: loadRows })
  }

  function goPage(page: number | null | undefined) {
    navigate(`/result?page=${page}`)
  }

  return (
    <div className="scope-result-list panel page-panel result-list-page">
      <div className="panel-title">检测结果</div>
      <div className="panel-body">
        {loading ? (
          <div className="page-loading">载入中...</div>
        ) : (
          <>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>上传机器人</th>
                    <th>设备ID</th>
                    <th>状态</th>
                    <th>位置</th>
                    <th>时间</th>
                    <th className="col-center">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((task) => (
                    <tr key={`task-${task.id}`}>
                      <td>{task.id}</td>
                      <td>{task.source_type || '-'}</td>
                      <td>{task.device_id || '-'}</td>
                      <td>{task.status || '-'}</td>
                      <td>{task.display_location || task.location || '-'}</td>
                      <td>{task.created_at || '-'}</td>
                      <td className="col-center col-nowrap">
                        <Link className="btn-detail result-list-square-btn" to={`/result/${task.id}`}>详情</Link>
                        {canDelete && (
                          <button type="button" className="btn-delete" style={{ marginLeft: 6 }} onClick={() => deleteTask(task.id)}>
                            删除
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {!rows.length && (
                    <tr>
                      <td colSpan={7} className="empty-state">暂无任务数据</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {pagination && (
              <div className="pagination-line">
                {pagination.has_prev && (
                  <a className="link-inline" href="#" onClick={(event) => { event.preventDefault(); goPage(pagination.prev_num) }}>
                    上一页
                  </a>
                )}
                {'  '}第 {pagination.page} 页{'  '}
                {pagination.has_next && (
                  <a className="link-inline" href="#" onClick={(event) => { event.preventDefault(); goPage(pagination.next_num) }}>
                    下一页
                  </a>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
