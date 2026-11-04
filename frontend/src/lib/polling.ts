/**
 * Run `task` every `intervalMs` while the page is visible.
 *
 * Polling stops while the tab is hidden (background tab, minimized window) so idle pages don't keep
 * hitting the API, and runs `task` once as soon as the tab is visible again so the data is fresh.
 * Returns a function that stops polling.
 */
export function pollWhileVisible(
  task: () => void,
  intervalMs: number,
  { immediate = true }: { immediate?: boolean } = {},
): () => void {
  let timer: number | null = null

  const start = () => {
    if (timer === null) {
      timer = window.setInterval(task, intervalMs)
    }
  }
  const pause = () => {
    if (timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  }
  const onVisibilityChange = () => {
    if (document.hidden) {
      pause()
    } else {
      task()
      start()
    }
  }

  if (immediate) {
    task()
  }
  if (!document.hidden) {
    start()
  }
  document.addEventListener('visibilitychange', onVisibilityChange)

  return () => {
    pause()
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }
}
