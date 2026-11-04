import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import CaptchaField from '../components/CaptchaField'
import { useCaptchaChallenge } from '../hooks/useCaptchaChallenge'
import { errorMessage, postJson } from '../lib/api'
import { fieldUpdater, trimFields } from '../lib/forms'
import { getSessionState, pushFlash, setSessionUser, type SessionUser } from '../stores/session'
import './AuthPages.css'

interface LoginResponse {
  user: SessionUser
  message?: string
  next?: string
}

const EMPTY_FORM = { username: '', password: '', captcha_text: '' }

export default function LoginPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [loading, setLoading] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const update = fieldUpdater(setForm)

  const { captcha, captchaLoading, cooldownLeft, loadCaptcha, handleCaptchaError } = useCaptchaChallenge({
    onResetText: () => setForm((current) => ({ ...current, captcha_text: '' })),
  })

  useEffect(() => {
    loadCaptcha()
  }, [loadCaptcha])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setLoading(true)
    try {
      const payload = await postJson<LoginResponse>('/api/web/login', {
        ...trimFields(form),
        captcha_id: captcha.id,
        next: searchParams.get('next') || getSessionState().nextPath,
      })
      setSessionUser(payload.user)
      pushFlash(payload.message || '登录成功', 'success')
      navigate(payload.next || '/', { replace: true })
    } catch (error) {
      pushFlash(errorMessage(error, '登录失败'), 'error')
      await handleCaptchaError(error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="scope-auth auth-shell">
      <div className="auth-surface">
        <aside className="auth-side">
          <p className="auth-kicker">Welcome Back</p>
          <h2>登录管理平台</h2>
          <p className="auth-desc">
            实时查看垃圾识别结果、机器人状态和热点分析，继续你的 TrashDet 管理流程。
          </p>
        </aside>

        <div className="auth-card">
          <form className="auth-form" onSubmit={submit}>
            <div className="field-block">
              <label htmlFor="username">用户名</label>
              <input id="username" value={form.username} onChange={update('username')} type="text" maxLength={50} required />
            </div>
            <div className="field-block">
              <label htmlFor="password">密码</label>
              <input id="password" value={form.password} onChange={update('password')} type="password" minLength={6} required />
            </div>
            <CaptchaField
              captcha={captcha}
              loading={captchaLoading}
              value={form.captcha_text}
              onChange={(value) => setForm((current) => ({ ...current, captcha_text: value }))}
              onRefresh={loadCaptcha}
            />
            <button type="submit" className="auth-submit" disabled={loading || cooldownLeft > 0}>
              {loading ? '登录中...' : cooldownLeft > 0 ? `请稍候 ${cooldownLeft}s` : '登录'}
            </button>
          </form>

          <div className="auth-links">
            还没有账号？<Link to="/register">立即注册</Link>
          </div>
        </div>
      </div>
    </section>
  )
}
