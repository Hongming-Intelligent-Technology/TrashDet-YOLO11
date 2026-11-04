import { onBeforeUnmount, reactive, ref } from 'vue'
import { getJson } from '../lib/api'
import { pushFlash } from '../stores/session'

export function useCaptchaChallenge(formState, options = {}) {
  const loadErrorMessage = options.loadErrorMessage || '验证码加载失败'
  const captchaLoading = ref(false)
  const cooldownLeft = ref(0)
  const captcha = reactive({
    enabled: true,
    id: '',
    image_data: '',
  })

  let cooldownTimer = null

  function clearCooldownTimer() {
    if (cooldownTimer) {
      window.clearInterval(cooldownTimer)
      cooldownTimer = null
    }
  }

  function startCooldown(seconds) {
    const activeSeconds = Number(seconds) || 0
    if (activeSeconds <= 0) {
      cooldownLeft.value = 0
      clearCooldownTimer()
      return
    }

    cooldownLeft.value = activeSeconds
    clearCooldownTimer()
    cooldownTimer = window.setInterval(() => {
      cooldownLeft.value = Math.max(0, cooldownLeft.value - 1)
      if (cooldownLeft.value <= 0) {
        clearCooldownTimer()
      }
    }, 1000)
  }

  function applyCaptchaPayload(payload) {
    if (!payload) {
      return
    }
    if (payload.captcha_id) {
      captcha.id = payload.captcha_id
    }
    if (payload.image_data) {
      captcha.image_data = payload.image_data
    }
    if (payload.captcha_enabled === false) {
      captcha.enabled = false
    }
    if (payload.force_refresh && formState && Object.prototype.hasOwnProperty.call(formState, 'captcha_text')) {
      formState.captcha_text = ''
    }
    if (payload.cooldown_seconds) {
      startCooldown(payload.cooldown_seconds)
    }
  }

  async function loadCaptcha() {
    captchaLoading.value = true
    try {
      const payload = await getJson('/api/web/captcha')
      captcha.enabled = payload.captcha_enabled !== false
      captcha.id = payload.captcha_id || ''
      captcha.image_data = payload.image_data || ''
      if (formState && Object.prototype.hasOwnProperty.call(formState, 'captcha_text')) {
        formState.captcha_text = ''
      }
    } catch (error) {
      captcha.enabled = false
      captcha.id = ''
      captcha.image_data = ''
      pushFlash(error.message || loadErrorMessage, 'error')
    } finally {
      captchaLoading.value = false
    }
  }

  async function handleCaptchaError(error) {
    const payload = error?.payload
    applyCaptchaPayload(payload)
    if (captcha.enabled && !payload?.captcha_id) {
      await loadCaptcha()
    }
  }

  onBeforeUnmount(() => {
    clearCooldownTimer()
  })

  return {
    captcha,
    captchaLoading,
    cooldownLeft,
    loadCaptcha,
    applyCaptchaPayload,
    handleCaptchaError,
  }
}
