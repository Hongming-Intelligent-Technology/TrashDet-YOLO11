import { useEffect, useMemo, useRef } from 'react'

/**
 * Keys of items that appeared since the previous non-empty version of `items`
 * (like Vue <transition-group>: the first render of the list is not animated).
 * Recomputed only when the `items` array itself changes.
 */
export function useNewKeys<T, K>(items: T[], getKey: (item: T) => K): Set<K> {
  const seenRef = useRef<Set<K> | null>(null)
  const getKeyRef = useRef(getKey)
  getKeyRef.current = getKey

  const newKeys = useMemo(() => {
    const seen = seenRef.current
    if (!seen) {
      return new Set<K>()
    }
    return new Set(items.map((item) => getKeyRef.current(item)).filter((key) => !seen.has(key)))
  }, [items])

  useEffect(() => {
    if (items.length) {
      seenRef.current = new Set(items.map((item) => getKeyRef.current(item)))
    }
  }, [items])

  return newKeys
}
