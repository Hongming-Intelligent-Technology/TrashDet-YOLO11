<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { postJson } from '../lib/api'
import { useCaptchaChallenge } from '../composables/useCaptchaChallenge'
import { pushFlash, setSessionUser, sessionState } from '../stores/session'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
  captcha_text: '',
})

const {
  captcha,
  captchaLoading,
  cooldownLeft,
  loadCaptcha,
  handleCaptchaError,
} = useCaptchaChallenge(form)

async function submit() {
  loading.value = true
  try {
    const payload = await postJson('/api/web/login', {
      ...form,
      captcha_id: captcha.id,
      next: route.query.next || sessionState.nextPath,
    })
    setSessionUser(payload.user)
    pushFlash(payload.message || '登录成功', 'success')
    await router.replace(payload.next || '/')
  } catch (error) {
    pushFlash(error.message || '登录失败', 'error')
    await handleCaptchaError(error)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadCaptcha()
})
</script>

<template>
  <section class="auth-shell">
    <div class="auth-surface">
      <aside class="auth-side">
        <p class="auth-kicker">Welcome Back</p>
        <h2>登录管理平台</h2>
        <p class="auth-desc">
          实时查看垃圾识别结果、机器人状态和热点分析，继续你的 EcoGuard 管理流程。
        </p>
      </aside>

      <div class="auth-card">
        <form class="auth-form" @submit.prevent="submit">
          <div class="field-block">
            <label for="username">用户名</label>
            <input id="username" v-model.trim="form.username" type="text" maxlength="50" required>
          </div>
          <div class="field-block">
            <label for="password">密码</label>
            <input id="password" v-model.trim="form.password" type="password" minlength="6" required>
          </div>
          <div v-if="captcha.enabled" class="field-block">
            <label for="captcha_text">图形验证码</label>
            <div class="captcha-row">
              <input id="captcha_text" v-model.trim="form.captcha_text" type="text" maxlength="8" required
                placeholder="请输入验证码">
              <img v-if="captcha.image_data" :src="captcha.image_data" alt="captcha" class="captcha-image">
              <button type="button" class="captcha-refresh" :disabled="captchaLoading" @click="loadCaptcha">
                {{ captchaLoading ? '加载中...' : '刷新' }}
              </button>
            </div>
          </div>
          <button type="submit" class="auth-submit" :disabled="loading || cooldownLeft > 0">
            {{ loading ? '登录中...' : (cooldownLeft > 0 ? `请稍候 ${cooldownLeft}s` : '登录') }}
          </button>
        </form>

        <div class="auth-links">
          还没有账号？<RouterLink to="/register">立即注册</RouterLink>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.auth-shell {
  min-height: 100vh;
  width: 100%;
  display: grid;
  align-items: center;
  padding: 20px clamp(14px, 3vw, 34px);
}

.auth-surface {
  width: min(1120px, 100%);
  min-height: min(86vh, 780px);
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(300px, 0.95fr) minmax(0, 1.05fr);
  align-items: stretch;
  border-radius: 24px;
  border: 1px solid rgba(37, 123, 102, 0.2);
  background: linear-gradient(145deg, rgba(248, 254, 251, 0.95), rgba(238, 248, 242, 0.94));
  box-shadow: 0 30px 64px rgba(31, 91, 75, 0.2);
  overflow: hidden;
}

.auth-side {
  padding: clamp(26px, 3vw, 38px) clamp(24px, 3vw, 36px);
  background:
    radial-gradient(circle at 16% 12%, rgba(62, 176, 146, 0.26), transparent 48%),
    radial-gradient(circle at 80% 90%, rgba(221, 159, 89, 0.22), transparent 44%),
    linear-gradient(160deg, rgba(233, 247, 240, 0.9), rgba(219, 239, 230, 0.72));
  border-right: 1px solid rgba(71, 143, 123, 0.24);
}

.auth-kicker {
  margin: 0 0 8px;
  font-size: 12px;
  letter-spacing: 0.8px;
  text-transform: uppercase;
  color: #27765f;
}

.auth-side h2 {
  margin: 0;
  font-size: clamp(24px, 2.8vw, 34px);
  color: #1e4f44;
}

.auth-desc {
  margin-top: 14px;
  line-height: 1.75;
  color: #4f746b;
}

.auth-card {
  width: min(100%, 520px);
  justify-self: center;
  align-self: center;
  padding: clamp(22px, 3vw, 32px);
  border-radius: 18px;
  border: 1px solid rgba(81, 148, 129, 0.22);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.84), rgba(244, 252, 247, 0.8));
  box-shadow: 0 16px 34px rgba(38, 104, 86, 0.14);
}

.auth-form {
  display: grid;
  gap: 10px;
  width: min(100%, 430px);
  margin: 0 auto;
}

.field-block {
  display: grid;
  gap: 6px;
}

.field-block label {
  color: #315f54;
  font-size: 13px;
}

.captcha-row {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) auto auto;
  gap: 8px;
  align-items: center;
}

.captcha-image {
  height: 40px;
  border-radius: 8px;
  border: 1px solid rgba(73, 146, 125, 0.32);
  background: rgba(255, 255, 255, 0.95);
}

.captcha-refresh {
  height: 40px;
  padding: 0 12px;
  border-radius: 10px;
}

.auth-submit {
  margin-top: 6px;
  min-height: 42px;
}

.auth-links {
  margin-top: 12px;
  color: #567c72;
  font-size: 13px;
}

.auth-links a {
  color: #1d856a;
}

@media (max-width: 900px) {
  .auth-shell {
    min-height: 100vh;
    padding: 12px;
  }

  .auth-surface {
    grid-template-columns: 1fr;
    min-height: auto;
  }

  .auth-side {
    border-right: 0;
    border-bottom: 1px solid rgba(120, 198, 205, 0.2);
    padding: 20px 18px;
  }

  .auth-card {
    width: 100%;
    padding: 20px 18px;
  }

  .captcha-row {
    grid-template-columns: 1fr;
  }

  .captcha-refresh,
  .captcha-image {
    width: 100%;
  }
}
</style>
