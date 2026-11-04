import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import CaptchaField from '../components/CaptchaField'
import { useCaptchaChallenge } from '../hooks/useCaptchaChallenge'
import { errorMessage, postJson } from '../lib/api'
import { fieldUpdater, trimFields } from '../lib/forms'
import { pushFlash } from '../stores/session'
import './AuthPages.css'

const EMPTY_FORM = {
  username: '',
  organization: '',
  password: '',
  confirm_password: '',
  security_code: '',
  captcha_text: '',
}

export default function RegisterPage() {
  const navigate = useNavigate()
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
      const payload = await postJson('/api/web/register', {
        ...trimFields(form),
        captcha_id: captcha.id,
      })
      pushFlash(payload.message || '注册成功，请登录', 'success')
      navigate('/login')
    } catch (error) {
      pushFlash(errorMessage(error, '注册失败'), 'error')
      await handleCaptchaError(error)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="scope-auth auth-shell">
      <div className="auth-surface">
        <aside className="auth-side">
          <p className="auth-kicker">Create Account</p>
          <h2>注册管理平台账号</h2>
          <p className="auth-desc">
            创建管理账号后即可使用上传检测、机器人管理和统计分析等完整功能。
          </p>
        </aside>

        <div className="auth-card">
          <form className="auth-form" onSubmit={submit}>
            <div className="field-block">
              <label htmlFor="username">用户名</label>
              <input id="username" value={form.username} onChange={update('username')} type="text" minLength={3} maxLength={50} required />
            </div>
            <div className="field-block">
              <label htmlFor="organization">所属单位</label>
              <input
                id="organization"
                value={form.organization}
                onChange={update('organization')}
                type="text"
                maxLength={120}
                required
                placeholder="例如：XX 环卫中心"
              />
            </div>
            <div className="field-block">
              <label htmlFor="password">密码</label>
              <input id="password" value={form.password} onChange={update('password')} type="password" minLength={6} required />
            </div>
            <div className="field-block">
              <label htmlFor="confirm_password">确认密码</label>
              <input
                id="confirm_password"
                value={form.confirm_password}
                onChange={update('confirm_password')}
                type="password"
                minLength={6}
                required
              />
            </div>
            <div className="field-block">
              <label htmlFor="security_code">安全码（用于后续身份校验）</label>
              <input
                id="security_code"
                value={form.security_code}
                onChange={update('security_code')}
                type="password"
                minLength={4}
                maxLength={32}
                required
              />
            </div>
            <CaptchaField
              captcha={captcha}
              loading={captchaLoading}
              value={form.captcha_text}
              onChange={(value) => setForm((current) => ({ ...current, captcha_text: value }))}
              onRefresh={loadCaptcha}
            />
            <button type="submit" className="auth-submit" disabled={loading || cooldownLeft > 0}>
              {loading ? '注册中...' : cooldownLeft > 0 ? `请稍候 ${cooldownLeft}s` : '注册'}
            </button>
          </form>

          <div className="auth-links">
            已有账号？<Link to="/login">去登录</Link>
          </div>
        </div>
      </div>
    </section>
  )
}
