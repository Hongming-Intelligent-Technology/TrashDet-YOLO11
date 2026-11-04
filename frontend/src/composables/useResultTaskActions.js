import { postJson } from '../lib/api'
import { pushFlash } from '../stores/session'

export async function confirmAndDeleteTask(taskId, options = {}) {
  const {
    confirmText = '确认删除该检测结果吗？',
    successMessage = '删除成功',
    errorMessage = '删除失败',
    onSuccess,
  } = options

  if (!window.confirm(confirmText)) {
    return false
  }

  try {
    const payload = await postJson(`/api/web/tasks/${taskId}/delete`, {})
    pushFlash(payload.message || successMessage, 'success')
    if (onSuccess) {
      await onSuccess(payload)
    }
    return true
  } catch (error) {
    pushFlash(error.message || errorMessage, 'error')
    return false
  }
}
