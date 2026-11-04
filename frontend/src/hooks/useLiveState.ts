import { useCallback, useRef, useState, type MutableRefObject } from 'react'

/**
 * useState plus a ref that is updated synchronously by the setter.
 * Imperative code (map handlers, timers) reads `ref.current` to see the latest value
 * immediately after setting it, like Vue's synchronous reactivity.
 */
export function useLiveState<T>(initial: T): [T, (next: T) => void, MutableRefObject<T>] {
  const [value, setValue] = useState(initial)
  const ref = useRef(value)
  const set = useCallback((next: T) => {
    ref.current = next
    setValue(next)
  }, [])
  return [value, set, ref]
}
