import { useEffect, useRef, useState } from 'react'
import { errorMessage, getJson } from '../../lib/api'
import { addressKeyOf, type Robot } from './shared'

/**
 * Street address of `robot`'s position, resolved by the backend while `active` is true.
 * Results are cached per rounded coordinate, and late responses for a robot that is no longer
 * selected are ignored.
 */
export function useRobotAddress(robot: Robot | null, active: boolean) {
  const [address, setAddress] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const addressKey = addressKeyOf(robot)
  const addressKeyRef = useRef(addressKey)
  addressKeyRef.current = addressKey
  const cacheRef = useRef(new Map<string, string>())
  const hasRobot = Boolean(robot)

  useEffect(() => {
    if (!active) {
      setLoading(false)
      setError('')
      return
    }
    if (!addressKey) return

    const cacheKey = addressKey
    const [lat, lng] = cacheKey.split(',').map(Number)
    const cached = cacheRef.current.get(cacheKey)
    if (cached !== undefined) {
      setAddress(cached)
      setError('')
      setLoading(false)
      return
    }

    setLoading(true)
    setError('')
    getJson<{ address?: string }>(`/api/robot/address?lat=${encodeURIComponent(lat)}&lng=${encodeURIComponent(lng)}`)
      .then((payload) => {
        const rawAddress = String(payload.address || '').trim()
        const resolved = (/^not\s*found$/i.test(rawAddress) ? '' : rawAddress) || '未解析到详细地址'
        cacheRef.current.set(cacheKey, resolved)
        if (addressKeyRef.current === cacheKey) {
          setAddress(resolved)
        }
      })
      .catch((lookupError) => {
        if (addressKeyRef.current === cacheKey) {
          setAddress(`坐标：${lat.toFixed(5)}, ${lng.toFixed(5)}`)
          setError(errorMessage(lookupError, '地址解析失败'))
        }
      })
      .finally(() => {
        if (addressKeyRef.current === cacheKey) {
          setLoading(false)
        }
      })
  }, [addressKey, active])

  // A robot without coordinates has no address to resolve.
  useEffect(() => {
    if (active && hasRobot && !addressKey) {
      setAddress('暂无定位信息')
      setError('')
      setLoading(false)
    }
  }, [active, hasRobot, addressKey])

  return { address, loading, error }
}
