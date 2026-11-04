import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, errorMessage, getJson } from '../lib/api'
import { pushFlash } from '../stores/session'

export interface CaptchaState {
  enabled: boolean
  id: string
  image_data: string
}

interface CaptchaPayload {
  captcha_id?: string
  image_data?: string
  captcha_enabled?: boolean
  force_refresh?: boolean
  cooldown_seconds?: number
}

interface Options {
  loadErrorMessage?: string
  /** Called whenever the typed captcha text should be cleared. */
  onResetText?: () => void
}

export function useCaptchaChallenge(options: Options = {}) {
  const loadErrorMessage = options.loadErrorMessage || '验证码加载失败'
  const onResetTextRef = useRef(options.onResetText)
  onResetTextRef.current = options.onResetText

  const [captchaLoading, setCaptchaLoading] = useState(false)
  const [cooldownLeft, setCooldownLeft] = useState(0)
  const [captcha, setCaptcha] = useState<CaptchaState>({ enabled: true, id: '', image_data: '' })
  const captchaRef = useRef(captcha)
  captchaRef.current = captcha
  const timerRef = useRef<number | null>(null)

  const clearCooldownTimer = useCallback(() => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const startCooldown = useCallback((seconds: unknown) => {
    const activeSeconds = Number(seconds) || 0
    clearCooldownTimer()
    if (activeSeconds <= 0) {
      setCooldownLeft(0)
      return
    }
    setCooldownLeft(activeSeconds)
    timerRef.current = window.setInterval(() => {
      setCooldownLeft((left) => {
        const next = Math.max(0, left - 1)
        if (next <= 0) {
          clearCooldownTimer()
        }
        return next
      })
    }, 1000)
  }, [clearCooldownTimer])

  useEffect(() => clearCooldownTimer, [clearCooldownTimer])

  const applyCaptchaPayload = useCallback((payload?: CaptchaPayload | null) => {
    if (!payload) {
      return
    }
    setCaptcha((current) => ({
      enabled: payload.captcha_enabled === false ? false : current.enabled,
      id: payload.captcha_id || current.id,
      image_data: payload.image_data || current.image_data,
    }))
    if (payload.force_refresh) {
      onResetTextRef.current?.()
    }
    if (payload.cooldown_seconds) {
      startCooldown(payload.cooldown_seconds)
    }
  }, [startCooldown])

  const loadCaptcha = useCallback(async () => {
    setCaptchaLoading(true)
    try {
      const payload = await getJson<CaptchaPayload>('/api/web/captcha')
      setCaptcha({
        enabled: payload.captcha_enabled !== false,
        id: payload.captcha_id || '',
        image_data: payload.image_data || '',
      })
      onResetTextRef.current?.()
    } catch (error) {
      setCaptcha({ enabled: false, id: '', image_data: '' })
      pushFlash(errorMessage(error, loadErrorMessage), 'error')
    } finally {
      setCaptchaLoading(false)
    }
  }, [loadErrorMessage])

  const handleCaptchaError = useCallback(async (error: unknown) => {
    const payload = error instanceof ApiError ? (error.payload as CaptchaPayload) : undefined
    applyCaptchaPayload(payload)
    const stillEnabled = payload?.captcha_enabled === false ? false : captchaRef.current.enabled
    if (stillEnabled && !payload?.captcha_id) {
      await loadCaptcha()
    }
  }, [applyCaptchaPayload, loadCaptcha])

  return {
    captcha,
    captchaLoading,
    cooldownLeft,
    loadCaptcha,
    applyCaptchaPayload,
    handleCaptchaError,
  }
}
