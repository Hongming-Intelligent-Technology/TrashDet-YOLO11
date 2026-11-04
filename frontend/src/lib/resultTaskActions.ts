import { errorMessage, postJson } from './api'
import { pushFlash } from '../stores/session'

interface DeleteTaskOptions {
  confirmText?: string
  successMessage?: string
  errorMessage?: string
  onSuccess?: (payload: Record<string, any>) => void | Promise<void>
}

export async function confirmAndDeleteTask(taskId: number | string, options: DeleteTaskOptions = {}): Promise<boolean> {
  const {
    confirmText = '确认删除该检测结果吗？',
    successMessage = '删除成功',
    errorMessage: failureMessage = '删除失败',
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
    pushFlash(errorMessage(error, failureMessage), 'error')
    return false
  }
}
