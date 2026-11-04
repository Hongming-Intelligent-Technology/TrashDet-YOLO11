import { useSyncExternalStore } from 'react'

export type ToastCategory = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id: number
  message: string
  category: ToastCategory
}

const DURATION_MS: Record<ToastCategory, number> = {
  success: 3000,
  info: 3500,
  warning: 5000,
  error: 6000,
}
const MAX_TOASTS = 4

let toasts: Toast[] = []
let nextId = 1
const listeners = new Set<() => void>()
const EMPTY: Toast[] = []

function emit() {
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function dismissToast(id: number) {
  toasts = toasts.filter((toast) => toast.id !== id)
  emit()
}

function normalizeCategory(category: string): ToastCategory {
  return category === 'error' || category === 'warning' || category === 'info' ? category : 'success'
}

export function showToast(message: string, category = 'success') {
  const kind = normalizeCategory(category)
  // Polling pages can report the same failure every few seconds: keep one copy on screen.
  if (toasts.some((toast) => toast.message === message && toast.category === kind)) {
    return
  }
  const toast = { id: nextId++, message, category: kind }
  toasts = [...toasts, toast].slice(-MAX_TOASTS)
  emit()
  window.setTimeout(() => dismissToast(toast.id), DURATION_MS[kind])
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(subscribe, () => toasts, () => EMPTY)
}
