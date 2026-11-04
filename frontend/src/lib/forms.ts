import type { ChangeEvent } from 'react'

/** Trim every string field, like Vue's `v-model.trim`. */
export function trimFields<T extends Record<string, unknown>>(form: T): T {
  return Object.fromEntries(
    Object.entries(form).map(([key, value]) => [key, typeof value === 'string' ? value.trim() : value]),
  ) as T
}

/** Returns an onChange handler factory that updates one field of a form state object. */
export function fieldUpdater<T extends Record<string, unknown>>(setForm: (update: (current: T) => T) => void) {
  return (key: keyof T) => (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const target = event.target
    const value = target instanceof HTMLInputElement && target.type === 'checkbox' ? target.checked : target.value
    setForm((current) => ({ ...current, [key]: value }))
  }
}
